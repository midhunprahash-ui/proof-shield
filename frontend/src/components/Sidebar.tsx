import { Icon } from "./Icon";

export type DashboardView = "cases" | "overview";

export function Sidebar({
  activeView,
  caseCount,
  onNavigate,
}: {
  activeView: DashboardView;
  caseCount: number;
  onNavigate: (view: DashboardView) => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand-block">
        <span className="brand-mark"><Icon name="shield" size={24} /></span>
        <div>
          <strong>ProofShield</strong>
          <span>Merchant console</span>
        </div>
      </div>

      <nav aria-label="Primary navigation" className="main-nav">
        <p className="nav-label">Workspace</p>
        <button
          aria-label="Overview"
          className={activeView === "overview" ? "nav-item active" : "nav-item"}
          onClick={() => onNavigate("overview")}
          type="button"
        >
          <Icon name="grid" />
          <span>Overview</span>
        </button>
        <button
          aria-label={`Dispute queue, ${caseCount} cases`}
          className={activeView === "cases" ? "nav-item active" : "nav-item"}
          onClick={() => onNavigate("cases")}
          type="button"
        >
          <Icon name="cases" />
          <span>Dispute queue</span>
          <span className="nav-count">{caseCount}</span>
        </button>
      </nav>

      <div className="sidebar-trust">
        <span className="trust-icon"><Icon name="lock" size={17} /></span>
        <div>
          <strong>Human-controlled</strong>
          <p>No response is submitted automatically.</p>
        </div>
      </div>

      <div className="sidebar-footer">
        <span className="live-pulse" />
        <span>Local workspace</span>
        <strong>v0.1</strong>
      </div>
    </aside>
  );
}
