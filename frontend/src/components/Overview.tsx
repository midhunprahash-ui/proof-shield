import type { CaseSummary } from "../types";
import { formatDateTime, formatMoney, shortId } from "../lib/format";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export function Overview({
  cases,
  onOpenCase,
  onOpenQueue,
}: {
  cases: CaseSummary[];
  onOpenCase: (disputeId: string) => void;
  onOpenQueue: () => void;
}) {
  const evidenceReady = cases.filter((item) => item.evidence_count >= 2).length;
  const needsEvidence = cases.length - evidenceReady;
  const recentCases = cases.slice(0, 4);

  return (
    <div className="page-stack">
      <section className="hero-panel">
        <div className="hero-copy">
          <StatusBadge tone="blue">Product not received</StatusBadge>
          <h1>Turn chargeback evidence into a defensible response.</h1>
          <p>
            ProofShield verifies merchant facts, refuses unsafe automation, and
            keeps every final action behind an explicit human decision.
          </p>
          <button className="primary-button" onClick={onOpenQueue} type="button">
            Review dispute queue <Icon name="arrow" size={18} />
          </button>
        </div>
        <div aria-label="ProofShield trust model" className="trust-orbit">
          <div className="orbit-ring orbit-one" />
          <div className="orbit-ring orbit-two" />
          <div className="orbit-core"><Icon name="shield" size={42} /></div>
          <span className="orbit-chip chip-one">Verify</span>
          <span className="orbit-chip chip-two">Cite</span>
          <span className="orbit-chip chip-three">Approve</span>
        </div>
      </section>

      <section aria-label="Queue metrics" className="metric-grid">
        <MetricCard
          accent="blue"
          detail="Across the active merchant queue"
          icon="cases"
          label="Open disputes"
          value={String(cases.length)}
        />
        <MetricCard
          accent="green"
          detail="At least two evidence records attached"
          icon="check"
          label="Evidence ready"
          value={String(evidenceReady)}
        />
        <MetricCard
          accent="amber"
          detail="Requires merchant evidence enrichment"
          icon="warning"
          label="Needs evidence"
          value={String(needsEvidence)}
        />
      </section>

      <section className="content-card recent-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Live queue</p>
            <h2>Recently updated disputes</h2>
          </div>
          <button className="text-button" onClick={onOpenQueue} type="button">
            View all <Icon name="arrow" size={16} />
          </button>
        </div>
        {recentCases.length === 0 ? (
          <EmptyQueue compact />
        ) : (
          <div className="recent-list">
            {recentCases.map((item) => (
              <button
                className="recent-row"
                key={item.dispute_id}
                onClick={() => onOpenCase(item.dispute_id)}
                type="button"
              >
                <span className="case-avatar">{item.currency.slice(0, 1)}</span>
                <span className="recent-main">
                  <strong>{shortId(item.dispute_id)}</strong>
                  <small>{shortId(item.order_id)} · {formatDateTime(item.updated_at)}</small>
                </span>
                <StatusBadge tone={item.evidence_count >= 2 ? "good" : "warning"}>
                  {item.evidence_count >= 2 ? "Evidence ready" : "Needs evidence"}
                </StatusBadge>
                <strong className="recent-amount">
                  {formatMoney(item.disputed_amount, item.currency)}
                </strong>
                <Icon name="chevron" size={17} />
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function MetricCard({
  accent,
  detail,
  icon,
  label,
  value,
}: {
  accent: "amber" | "blue" | "green";
  detail: string;
  icon: "cases" | "check" | "warning";
  label: string;
  value: string;
}) {
  return (
    <article className={`metric-card metric-${accent}`}>
      <span className="metric-icon"><Icon name={icon} /></span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <p>{detail}</p>
      </div>
    </article>
  );
}

export function EmptyQueue({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "empty-state compact" : "empty-state"}>
      <span><Icon name="shield" size={30} /></span>
      <div>
        <h3>No disputes in the queue</h3>
        <p>Verified Razorpay dispute events will appear here automatically.</p>
      </div>
    </div>
  );
}
