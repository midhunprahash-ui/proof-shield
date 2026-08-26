import { formatDateTime } from "../lib/format";
import type { CaseHistoryEntry } from "../types";
import { Icon } from "./Icon";

const actionLabels: Record<CaseHistoryEntry["action"], string> = {
  CASE_CREATED: "Case created",
  CASE_CLAIMED: "Case assigned",
  FILE_UPLOADED: "Source uploaded",
  EVIDENCE_ADDED: "Evidence recorded",
  ASSESSED: "Case assessed",
  DRAFT_CREATED: "Response drafted",
  DRAFT_APPROVED: "Draft approved",
  DRAFT_REJECTED: "Draft rejected",
};

export function AuditTimeline({ history }: { history: CaseHistoryEntry[] }) {
  return (
    <section className="detail-card timeline-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Append-only record</p>
          <h3>Case audit timeline</h3>
        </div>
        <Icon name="activity" />
      </div>
      <ol className="timeline-list">
        {history.map((entry) => (
          <li key={entry.sequence}>
            <span className="timeline-marker"><Icon name="check" size={14} /></span>
            <div>
              <strong>{actionLabels[entry.action]}</strong>
              <p>{entry.detail}</p>
              <small>{formatDateTime(entry.recorded_at)}</small>
            </div>
            <code>#{entry.sequence}</code>
          </li>
        ))}
      </ol>
    </section>
  );
}
