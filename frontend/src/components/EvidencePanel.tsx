import { useState } from "react";

import type { ProofShieldApi } from "../api";
import { evidenceTypeLabel, formatBytes, formatDateTime, shortId } from "../lib/format";
import type {
  DisputeCase,
  EvidenceExtractionProposal,
  EvidenceFileMetadata,
  EvidenceSubmission,
  EvidenceType,
} from "../types";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export function EvidencePanel({
  api,
  caseData,
  files,
  notify,
  onChanged,
}: {
  api: ProofShieldApi;
  caseData: DisputeCase;
  files: EvidenceFileMetadata[];
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
                <article className="evidence-record" key={evidence.evidence_id}>
                  <span className="file-kind"><Icon name="file" size={18} /></span>
                  <div>
                    <strong>{evidenceTypeLabel(evidence.evidence_type)}</strong>
                    <span>{evidence.source_name ?? shortId(evidence.evidence_id)}</span>
                  </div>
                  <StatusBadge tone={evidence.source_verified ? "good" : "warning"}>
                    {evidence.source_verified ? "Verified" : "Unverified"}
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
            The local baseline reads exact labels from JSON or text. Every value
            keeps a source reference and must be reviewed before submission.
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
