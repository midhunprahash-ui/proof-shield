import { useState } from "react";

import type { ProofShieldApi } from "../api";
import {
  deadlineState,
  decisionLabel,
  formatDate,
  formatMoney,
  shortId,
} from "../lib/format";
import type { Assessment, CaseWorkspaceData, OperatorIdentity } from "../types";
import { AuditTimeline } from "./AuditTimeline";
import { EvidencePanel } from "./EvidencePanel";
import { Icon } from "./Icon";
import { ResponsePanel } from "./ResponsePanel";
import { StatusBadge, type StatusTone } from "./StatusBadge";

type WorkspaceTab = "audit" | "evidence" | "response" | "summary";

const tabs: { id: WorkspaceTab; label: string }[] = [
  { id: "summary", label: "Summary" },
  { id: "evidence", label: "Evidence" },
  { id: "response", label: "Response" },
  { id: "audit", label: "Audit trail" },
];

export function CaseWorkspace({
  api,
  data,
  notify,
  onBack,
  onRefresh,
  operator,
}: {
  api: ProofShieldApi;
  data: CaseWorkspaceData;
  notify: (message: string, tone?: "danger" | "good") => void;
  onBack: () => void;
  onRefresh: () => Promise<void>;
  operator: OperatorIdentity;
}) {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("summary");
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [assessing, setAssessing] = useState(false);
  const deadline = deadlineState(data.case.respond_by);

  async function assess() {
    setAssessing(true);
    try {
      const result = await api.assess(data.case.dispute_id);
      setAssessment(result);
      notify(`Assessment complete: ${decisionLabel(result.decision)}.`, "good");
      await onRefresh();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Case could not be assessed.", "danger");
    } finally {
      setAssessing(false);
    }
  }

  return (
    <div className="case-workspace">
      <button className="back-button" onClick={onBack} type="button">
        <Icon name="chevron" size={16} /> Back to queue
      </button>

      <header className="case-header">
        <div>
          <div className="case-title-line">
            <p className="eyebrow">Product not received</p>
            <StatusBadge tone={deadline.tone}>{deadline.label}</StatusBadge>
          </div>
          <h1>Dispute {shortId(data.case.dispute_id)}</h1>
          <p>
            Order {shortId(data.case.order_id)} · Payment {shortId(data.case.payment_id)}
          </p>
        </div>
        <div className="case-value">
          <span>Disputed amount</span>
          <strong>{formatMoney(data.case.disputed_amount, data.case.currency)}</strong>
          <small>Respond by {formatDate(data.case.respond_by)}</small>
        </div>
      </header>

      <nav aria-label="Case sections" className="workspace-tabs">
        {tabs.map((tab) => (
          <button
            aria-current={activeTab === tab.id ? "page" : undefined}
            className={activeTab === tab.id ? "active" : ""}
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            type="button"
          >
            {tab.label}
            {tab.id === "evidence" ? <span>{data.case.evidence.length}</span> : null}
          </button>
        ))}
      </nav>

      {activeTab === "summary" ? (
        <SummaryPanel
          assessment={assessment}
          assessing={assessing}
          data={data}
          onAssess={() => void assess()}
          onOpenEvidence={() => setActiveTab("evidence")}
          onOpenResponse={() => setActiveTab("response")}
        />
      ) : null}
      {activeTab === "evidence" ? (
        <EvidencePanel
          api={api}
          caseData={data.case}
          consistency={data.consistency}
          files={data.files}
          resolutions={data.resolutions}
          notify={notify}
          onChanged={onRefresh}
        />
      ) : null}
      {activeTab === "response" ? (
        <ResponsePanel
          api={api}
          disputeId={data.case.dispute_id}
          drafts={data.drafts}
          notify={notify}
          onChanged={onRefresh}
          operator={operator}
        />
      ) : null}
      {activeTab === "audit" ? <AuditTimeline history={data.history} /> : null}
    </div>
  );
}

function SummaryPanel({
  assessment,
  assessing,
  data,
  onAssess,
  onOpenEvidence,
  onOpenResponse,
}: {
  assessment: Assessment | null;
  assessing: boolean;
  data: CaseWorkspaceData;
  onAssess: () => void;
  onOpenEvidence: () => void;
  onOpenResponse: () => void;
}) {
  const coverage = Math.min(100, data.case.evidence.length * 50);
  const checks = assessment?.checks ?? [];
  const assessmentTone: StatusTone = assessment
    ? assessment.decision === "SAFE_TO_DRAFT"
      ? "good"
      : assessment.decision === "NEEDS_REVIEW"
        ? "warning"
        : "danger"
    : "muted";

  return (
    <div className="panel-stack">
      <section className="workspace-grid summary-grid">
        <article className="detail-card assessment-card span-two">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Deterministic verifier</p>
              <h3>Case readiness assessment</h3>
            </div>
            <StatusBadge tone={assessmentTone}>
              {assessment ? decisionLabel(assessment.decision) : "Not assessed"}
            </StatusBadge>
          </div>
          {assessment ? (
            <>
              <div className="score-row">
                <div>
                  <strong>{Math.round(assessment.evidence_score * 100)}%</strong>
                  <span>evidence confidence</span>
                </div>
                <p>{assessment.summary}</p>
              </div>
              <div className="check-list">
                {checks.map((check) => (
                  <div key={check.code}>
                    <span className={`check-icon check-${check.outcome.toLowerCase()}`}>
                      <Icon name={check.outcome === "PASS" ? "check" : "warning"} size={15} />
                    </span>
                    <p><strong>{check.code.replaceAll("_", " ").toLowerCase()}</strong>{check.message}</p>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="assessment-prompt">
              <span><Icon name="shield" size={30} /></span>
              <div>
                <strong>Run exact checks before drafting</strong>
                <p>IDs, amounts, deadline, delivery status and file provenance are checked without an AI model.</p>
              </div>
              <button className="primary-button" disabled={assessing} onClick={onAssess} type="button">
                {assessing ? "Assessing…" : "Assess case"}
              </button>
            </div>
          )}
        </article>

        <article className="detail-card readiness-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Evidence coverage</p>
              <h3>{coverage}% ready</h3>
            </div>
            <Icon name="file" />
          </div>
          <div className="progress-track"><span style={{ width: `${coverage}%` }} /></div>
          <ul>
            <li><Icon name={data.files.length > 0 ? "check" : "warning"} size={15} /> {data.files.length} source files</li>
            <li><Icon name={data.case.evidence.length > 0 ? "check" : "warning"} size={15} /> {data.case.evidence.length} verified records</li>
            <li><Icon name={data.drafts.length > 0 ? "check" : "clock"} size={15} /> {data.drafts.length} response drafts</li>
          </ul>
          <button className="text-button" onClick={onOpenEvidence} type="button">Manage evidence <Icon name="arrow" size={15} /></button>
        </article>
      </section>

      <section className="workspace-grid fact-grid">
        <FactCard label="Payment status" tone="good" value={data.case.payment.captured ? "Captured" : "Not captured"} />
        <FactCard label="Currency" tone="blue" value={data.case.currency} />
        <FactCard label="Response draft" tone={data.drafts.length > 0 ? "good" : "warning"} value={data.drafts.length > 0 ? "Prepared" : "Not created"} />
        <button className="detail-card next-step-card" onClick={onOpenResponse} type="button">
          <span><Icon name="arrow" /></span>
          <div><small>Next control</small><strong>Review response</strong></div>
        </button>
      </section>
    </div>
  );
}

function FactCard({ label, tone, value }: { label: string; tone: StatusTone; value: string }) {
  return (
    <article className="detail-card fact-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <StatusBadge dot tone={tone}>Verified state</StatusBadge>
    </article>
  );
}
