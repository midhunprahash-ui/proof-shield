import { useMemo, useState } from "react";

import type { ProofShieldApi } from "../api";
import { evidenceTypeLabel, formatBytes, formatDateTime, shortId } from "../lib/format";
import type {
  DisputeCase,
  EvidenceConsistencyReport,
  EvidenceExtractionProposal,
  EvidenceFileMetadata,
  EvidenceResolution,
  EvidenceSubmission,
  EvidenceType,
} from "../types";
import { Icon } from "./Icon";
import { EvidenceResolutionPanel } from "./EvidenceResolutionPanel";
import { StatusBadge } from "./StatusBadge";

const CONSISTENCY_STATUS = {
  CONSISTENT: { label: "Sources agree", tone: "good" as const },
  CONFLICTS_FOUND: { label: "Conflicts found", tone: "danger" as const },
  INCOMPLETE: { label: "Evidence incomplete", tone: "warning" as const },
  UNVERIFIED_SOURCES: { label: "Unverified sources", tone: "warning" as const },
};

const REQUIREMENT_TONE = {
  SATISFIED: "good" as const,
  MISSING: "danger" as const,
  UNVERIFIED: "warning" as const,
  OPTIONAL: "muted" as const,
};

const FACT_TONE = {
  MATCH: "good" as const,
  CONFLICT: "danger" as const,
  MISSING: "warning" as const,
  UNVERIFIED: "warning" as const,
};

export function EvidencePanel({
  api,
  caseData,
  consistency,
  files,
  resolutions,
  notify,
  onChanged,
}: {
  api: ProofShieldApi;
  caseData: DisputeCase;
  consistency: EvidenceConsistencyReport;
  files: EvidenceFileMetadata[];
  resolutions: EvidenceResolution[];
  notify: (message: string, tone?: "danger" | "good") => void;
  onChanged: () => Promise<void>;
}) {
  const [uploading, setUploading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [proposal, setProposal] = useState<EvidenceExtractionProposal | null>(null);
  const [evidenceType, setEvidenceType] = useState<EvidenceType>("INVOICE");
  const [sourceFileId, setSourceFileId] = useState(files[0]?.file_id ?? "");
  const [confirmed, setConfirmed] = useState(false);
  const [orderId, setOrderId] = useState(caseData.order_id);
  const [paymentId, setPaymentId] = useState(caseData.payment_id);
  const [amount, setAmount] = useState(caseData.disputed_amount);
  const [deliveryStatus, setDeliveryStatus] = useState("delivered");
  const [customerAcknowledged, setCustomerAcknowledged] = useState(false);
  const [text, setText] = useState("");
  const resolutionByEvidenceId = useMemo(
    () => new Map(resolutions.map((resolution) => [resolution.evidence_id, resolution])),
    [resolutions],
  );

  async function uploadFile(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    try {
      const uploaded = await api.uploadFile(caseData.dispute_id, file);
      setSourceFileId(uploaded.file_id);
      notify(`${uploaded.original_name} uploaded and hashed.`, "good");
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "File upload failed.", "danger");
    } finally {
      setUploading(false);
    }
  }

  async function addEvidence() {
    if (!sourceFileId || !confirmed) return;
    const submission: EvidenceSubmission = {
      evidence_id: `evidence_${evidenceType.toLowerCase()}_${crypto.randomUUID()}`,
      evidence_type: evidenceType,
      source_file_id: sourceFileId,
      human_confirmed_source: true,
    };
    if (orderId.trim()) submission.order_id = orderId.trim();
    if (paymentId.trim()) submission.payment_id = paymentId.trim();
    if (evidenceType === "INVOICE" && amount.trim()) submission.amount = amount.trim();
    if (evidenceType === "DELIVERY_PROOF") {
      submission.delivery_status = deliveryStatus.trim();
    }
    if (evidenceType === "CUSTOMER_COMMUNICATION") {
      submission.customer_acknowledged_delivery = customerAcknowledged;
      if (text.trim()) submission.text = text.trim();
    }

    setAdding(true);
    try {
      await api.addEvidence(caseData.dispute_id, submission);
      notify(`${evidenceTypeLabel(evidenceType)} added to the case.`, "good");
      setConfirmed(false);
      setText("");
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Evidence could not be added.", "danger");
    } finally {
      setAdding(false);
    }
  }

  async function extractProposal() {
    if (!sourceFileId) return;
    setExtracting(true);
    try {
      const result = await api.extractEvidence(
        caseData.dispute_id,
        sourceFileId,
        evidenceType,
      );
      setProposal(result);
      setConfirmed(false);
      notify(
        result.claims.length > 0
          ? `${result.claims.length} proposed facts found. Review every value before use.`
          : "No supported labelled facts were found.",
        result.claims.length > 0 ? "good" : "danger",
      );
    } catch (error) {
      setProposal(null);
      notify(error instanceof Error ? error.message : "Extraction failed.", "danger");
    } finally {
      setExtracting(false);
    }
  }

  function useProposal() {
    if (!proposal) return;
    const claims = new Map(proposal.claims.map((claim) => [claim.field, claim.value]));
    const proposedOrder = claims.get("order_id");
    const proposedPayment = claims.get("payment_id");
    const proposedAmount = claims.get("amount");
    const proposedStatus = claims.get("delivery_status");
    const proposedAcknowledgement = claims.get("customer_acknowledged_delivery");
    const proposedText = claims.get("text");
    if (typeof proposedOrder === "string") setOrderId(proposedOrder);
    if (typeof proposedPayment === "string") setPaymentId(proposedPayment);
    if (typeof proposedAmount === "string") setAmount(proposedAmount);
    if (typeof proposedStatus === "string") setDeliveryStatus(proposedStatus);
    if (typeof proposedAcknowledgement === "boolean") {
      setCustomerAcknowledged(proposedAcknowledgement);
    }
    if (typeof proposedText === "string") setText(proposedText);
    setConfirmed(false);
    notify("Proposal copied into the review form. It is still unverified.", "good");
  }

  return (
    <div className="panel-stack">
      <ConsistencyReport report={consistency} />
      <section className="workspace-grid evidence-summary-grid">
        <article className="detail-card span-two">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Structured evidence</p>
              <h3>Verified case records</h3>
            </div>
            <StatusBadge tone={caseData.evidence.length >= 2 ? "good" : "warning"}>
              {caseData.evidence.length} records
            </StatusBadge>
          </div>
          {caseData.evidence.length === 0 ? (
            <div className="inline-empty">
              <Icon name="file" />
              <p>No structured evidence has been attached yet.</p>
            </div>
          ) : (
            <div className="evidence-record-list">
              {caseData.evidence.map((evidence) => (
                <article
                  className={resolutionByEvidenceId.has(evidence.evidence_id)
                    ? "evidence-record evidence-record-resolved"
                    : "evidence-record"}
                  key={evidence.evidence_id}
                >
                  <span className="file-kind"><Icon name="file" size={18} /></span>
                  <div>
                    <strong>{evidenceTypeLabel(evidence.evidence_type)}</strong>
                    <span>{evidence.source_name ?? shortId(evidence.evidence_id)}</span>
                  </div>
                  <StatusBadge
                    tone={resolutionByEvidenceId.has(evidence.evidence_id)
                      ? "muted"
                      : evidence.source_verified ? "good" : "warning"}
                  >
                    {resolutionByEvidenceId.has(evidence.evidence_id)
                      ? "Resolved"
                      : evidence.source_verified ? "Verified" : "Unverified"}
                  </StatusBadge>
                  <code>{evidence.source_sha256 ? shortId(evidence.source_sha256, 6) : "No hash"}</code>
                </article>
              ))}
            </div>
          )}
        </article>

        <article className="detail-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Private storage</p>
              <h3>Source files</h3>
            </div>
            <span className="card-count">{files.length}</span>
          </div>
          <div className="source-file-list">
            {files.map((file) => (
              <div className="source-file" key={file.file_id}>
                <span><Icon name="file" size={17} /></span>
                <div>
                  <strong>{file.original_name}</strong>
                  <small>{formatBytes(file.size_bytes)} · {formatDateTime(file.created_at)}</small>
                </div>
              </div>
            ))}
            {files.length === 0 ? <p className="muted-copy">No source files uploaded.</p> : null}
          </div>
        </article>
      </section>

      <EvidenceResolutionPanel
        api={api}
        caseData={caseData}
        notify={notify}
        onChanged={onChanged}
        resolutions={resolutions}
      />

      <section className="workspace-grid composer-grid">
        <article className="detail-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Step 1</p>
              <h3>Upload a source</h3>
            </div>
            <Icon name="upload" />
          </div>
          <p className="muted-copy">
            PDF, PNG, JPEG, JSON or UTF-8 text. Maximum 5 MB. Files are private and
            hashed before registration.
          </p>
          <label className={uploading ? "upload-drop busy" : "upload-drop"}>
            <Icon name="upload" size={24} />
            <strong>{uploading ? "Uploading…" : "Choose an evidence file"}</strong>
            <span>The original file never enters the response draft directly.</span>
            <input
              accept=".pdf,.png,.jpg,.jpeg,.json,.txt,application/pdf,image/png,image/jpeg,application/json,text/plain"
              disabled={uploading}
              onChange={(event) => void uploadFile(event.target.files?.[0])}
              type="file"
            />
          </label>
        </article>

        <article className="detail-card extraction-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Step 2</p>
              <h3>Extract proposed facts</h3>
            </div>
            <StatusBadge tone="warning">Never auto-verified</StatusBadge>
          </div>
          <p className="muted-copy">
            JSON and text use exact-label parsing. PDF and image sources use the
            configured local OCR provider. Every value keeps a source reference
            and must be reviewed before submission.
          </p>
          <div className="form-grid extraction-selectors">
            <label>
              Evidence type
              <select
                onChange={(event) => {
                  setEvidenceType(event.target.value as EvidenceType);
                  setProposal(null);
                  setConfirmed(false);
                }}
                value={evidenceType}
              >
                <option value="INVOICE">Invoice</option>
                <option value="DELIVERY_PROOF">Delivery proof</option>
                <option value="CUSTOMER_COMMUNICATION">Customer communication</option>
              </select>
            </label>
            <label>
              Source file
              <select
                disabled={files.length === 0}
                onChange={(event) => {
                  setSourceFileId(event.target.value);
                  setProposal(null);
                  setConfirmed(false);
                }}
                value={sourceFileId}
              >
                <option value="">Select an uploaded file</option>
                {files.map((file) => (
                  <option key={file.file_id} value={file.file_id}>{file.original_name}</option>
                ))}
              </select>
            </label>
          </div>
          <button
            className="secondary-button full-button"
            disabled={!sourceFileId || extracting}
            onClick={() => void extractProposal()}
            type="button"
          >
            <Icon name="activity" size={16} />
            {extracting ? "Extracting…" : "Propose facts from source"}
          </button>
          {proposal ? (
            <div className="extraction-proposal">
              <p className="muted-copy">
                Extractor: <code>{proposal.extractor}</code>
              </p>
              {proposal.claims.map((claim) => (
                <div key={claim.field}>
                  <span>{claim.field.replaceAll("_", " ")}</span>
                  <strong>{String(claim.value)}</strong>
                  <small>
                    {claim.source_reference} · {Math.round(claim.confidence * 100)} score
                  </small>
                </div>
              ))}
              {proposal.warnings.map((warning) => (
                <p className="extraction-warning" key={warning}>
                  <Icon name="warning" size={14} /> {warning}
                </p>
              ))}
              {proposal.claims.length > 0 ? (
                <button className="text-button" onClick={useProposal} type="button">
                  Copy into review form <Icon name="arrow" size={15} />
                </button>
              ) : null}
            </div>
          ) : null}
        </article>

        <article className="detail-card span-two">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Step 3</p>
              <h3>Record reviewed facts</h3>
            </div>
            <StatusBadge tone="blue">Human confirmed</StatusBadge>
          </div>
          <div className="form-grid evidence-form">
            <label>
              Evidence type
              <select
                onChange={(event) => {
                  setEvidenceType(event.target.value as EvidenceType);
                  setProposal(null);
                  setConfirmed(false);
                }}
                value={evidenceType}
              >
                <option value="INVOICE">Invoice</option>
                <option value="DELIVERY_PROOF">Delivery proof</option>
                <option value="CUSTOMER_COMMUNICATION">Customer communication</option>
              </select>
            </label>
            <label>
              Source file
              <select
                disabled={files.length === 0}
                onChange={(event) => {
                  setSourceFileId(event.target.value);
                  setProposal(null);
                  setConfirmed(false);
                }}
                value={sourceFileId}
              >
                <option value="">Select an uploaded file</option>
                {files.map((file) => (
                  <option key={file.file_id} value={file.file_id}>{file.original_name}</option>
                ))}
              </select>
            </label>
            <label>
              Order ID
              <input onChange={(event) => setOrderId(event.target.value)} value={orderId} />
            </label>
            <label>
              Payment ID
              <input onChange={(event) => setPaymentId(event.target.value)} value={paymentId} />
            </label>
            {evidenceType === "INVOICE" ? (
              <label>
                Invoice amount
                <input onChange={(event) => setAmount(event.target.value)} value={amount} />
              </label>
            ) : null}
            {evidenceType === "DELIVERY_PROOF" ? (
              <label>
                Delivery status
                <input
                  onChange={(event) => setDeliveryStatus(event.target.value)}
                  value={deliveryStatus}
                />
              </label>
            ) : null}
            {evidenceType === "CUSTOMER_COMMUNICATION" ? (
              <>
                <label className="span-two-field">
                  Reviewed communication summary
                  <textarea
                    onChange={(event) => setText(event.target.value)}
                    placeholder="Record only facts visible in the uploaded source."
                    rows={3}
                    value={text}
                  />
                </label>
                <label className="check-field">
                  <input
                    checked={customerAcknowledged}
                    onChange={(event) => setCustomerAcknowledged(event.target.checked)}
                    type="checkbox"
                  />
                  Customer acknowledged delivery
                </label>
              </>
            ) : null}
            <label className="check-field confirmation-field">
              <input
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                type="checkbox"
              />
              I reviewed this source and confirm the recorded facts
            </label>
          </div>
          <div className="form-actions">
            <span>Records are append-only after submission.</span>
            <button
              className="primary-button"
              disabled={adding || !confirmed || !sourceFileId}
              onClick={() => void addEvidence()}
              type="button"
            >
              {adding ? "Adding evidence…" : "Add verified evidence"}
            </button>
          </div>
        </article>
      </section>
    </div>
  );
}

function ConsistencyReport({ report }: { report: EvidenceConsistencyReport }) {
  const status = CONSISTENCY_STATUS[report.status];

  return (
    <section className="detail-card consistency-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Cross-source consistency</p>
          <h3>Compare every confirmed record</h3>
        </div>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
      </div>
      <p className="muted-copy consistency-summary">
        {report.summary} This report never decides the chargeback. Deterministic
        conflicts block drafting until an operator corrects or resolves the evidence.
      </p>
      <div className="consistency-metrics" aria-label="Consistency finding counts">
        <span><strong>{report.conflict_count}</strong> conflicts</span>
        <span><strong>{report.missing_count}</strong> missing checks</span>
        <span><strong>{report.unverified_count}</strong> unverified sources</span>
      </div>
      <div className="consistency-layout">
        <div className="requirement-list">
          <h4>Source coverage</h4>
          {report.requirements.map((requirement) => (
            <div key={requirement.evidence_type}>
              <div>
                <strong>{evidenceTypeLabel(requirement.evidence_type)}</strong>
                <small>{requirement.message}</small>
              </div>
              <StatusBadge tone={REQUIREMENT_TONE[requirement.outcome]}>
                {requirement.outcome.toLowerCase()}
              </StatusBadge>
            </div>
          ))}
        </div>
        <div className="consistency-fact-list">
          <h4>Fact comparison</h4>
          {report.facts.map((fact) => (
            <article key={fact.field}>
              <div className="consistency-fact-heading">
                <strong>{fact.field.replaceAll("_", " ")}</strong>
                <StatusBadge tone={FACT_TONE[fact.outcome]}>
                  {fact.outcome.toLowerCase()}
                </StatusBadge>
              </div>
              <p>{fact.message}</p>
              {fact.expected_value !== null ? (
                <small>Expected: <code>{String(fact.expected_value)}</code></small>
              ) : null}
              <ul>
                {fact.observations.map((observation) => (
                  <li key={observation.evidence_id}>
                    <span>{observation.source_name ?? shortId(observation.evidence_id)}</span>
                    <code>{String(observation.value)}</code>
                    {!observation.source_verified ? <em>unverified</em> : null}
                  </li>
                ))}
              </ul>
              {fact.missing_from_evidence_ids.length > 0 ? (
                <small>
                  Missing from: {fact.missing_from_evidence_ids.map((id) => shortId(id)).join(", ")}
                </small>
              ) : null}
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
