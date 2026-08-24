import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiUrlFromDocument, ProofShieldApi } from "./api";
import { CaseQueue } from "./components/CaseQueue";
import { CaseWorkspace } from "./components/CaseWorkspace";
import { Icon } from "./components/Icon";
import { OperatorAccessDialog } from "./components/OperatorAccessDialog";
import { Overview } from "./components/Overview";
import { Sidebar, type DashboardView } from "./components/Sidebar";
import type { CaseSummary, CaseWorkspaceData } from "./types";

interface ToastState {
  message: string;
  tone: "danger" | "good";
}

export function App() {
  const api = useMemo(() => new ProofShieldApi(apiUrlFromDocument()), []);
  const [activeView, setActiveView] = useState<DashboardView>("overview");
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<CaseWorkspaceData | null>(null);
  const [loadingCases, setLoadingCases] = useState(true);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operatorSecret, setOperatorSecret] = useState("");
  const [operatorDialogOpen, setOperatorDialogOpen] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const notify = useCallback((message: string, tone: "danger" | "good" = "good") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4200);
  }, []);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const loadCases = useCallback(async (signal?: AbortSignal) => {
    const nextCases = await api.listCases(signal);
    setCases(nextCases);
    setLoadError(null);
  }, [api]);

  useEffect(() => {
    const controller = new AbortController();
    setLoadingCases(true);
    loadCases(controller.signal)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : "ProofShield API is unavailable.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingCases(false);
      });
    return () => controller.abort();
  }, [loadCases]);

  useEffect(() => {
    if (!selectedId) {
      setWorkspace(null);
      return;
    }
    const controller = new AbortController();
    setLoadingWorkspace(true);
    api
      .getWorkspace(selectedId, controller.signal)
      .then((nextWorkspace) => {
        setWorkspace(nextWorkspace);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setLoadError(error instanceof Error ? error.message : "Case could not be loaded.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingWorkspace(false);
      });
    return () => controller.abort();
  }, [api, selectedId]);

  const refreshWorkspace = useCallback(async () => {
    if (!selectedId) return;
    const [nextWorkspace] = await Promise.all([
      api.getWorkspace(selectedId),
      loadCases(),
    ]);
    setWorkspace(nextWorkspace);
  }, [api, loadCases, selectedId]);

  function navigate(view: DashboardView) {
    setSelectedId(null);
    setActiveView(view);
  }

  function openCase(disputeId: string) {
    setActiveView("cases");
    setSelectedId(disputeId);
  }

  async function retry() {
    setLoadingCases(true);
    try {
      await loadCases();
      if (selectedId) setWorkspace(await api.getWorkspace(selectedId));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "ProofShield API is unavailable.");
    } finally {
      setLoadingCases(false);
    }
  }

  return (
    <div className="app-shell">
      <Sidebar activeView={activeView} caseCount={cases.length} onNavigate={navigate} />
      <div className="app-column">
        <header className="topbar">
          <div>
            <span className="live-pulse" />
            <span>Supabase-backed local API</span>
          </div>
          <div className="topbar-actions">
            <button
              aria-label="Refresh dashboard data"
              className="icon-button"
              disabled={loadingCases || loadingWorkspace}
              onClick={() => void retry()}
              type="button"
            >
              <Icon name="refresh" size={18} />
            </button>
            {operatorSecret ? (
              <button className="operator-pill unlocked" onClick={() => setOperatorSecret("")} type="button">
                <Icon name="lock" size={15} /> Operator unlocked · clear
              </button>
            ) : (
              <button className="operator-pill" onClick={() => setOperatorDialogOpen(true)} type="button">
                <Icon name="lock" size={15} /> Operator access
              </button>
            )}
          </div>
        </header>

        <main className="main-content">
          {loadError &&
          (cases.length === 0 || (selectedId !== null && workspace === null)) ? (
            <ErrorPanel error={loadError} loading={loadingCases} onRetry={() => void retry()} />
          ) : selectedId ? (
            loadingWorkspace && !workspace ? (
              <LoadingPanel label="Loading verified case workspace…" />
            ) : workspace ? (
              <CaseWorkspace
                api={api}
                data={workspace}
                key={workspace.case.dispute_id}
                notify={notify}
                onBack={() => setSelectedId(null)}
                onRefresh={refreshWorkspace}
                onRequestOperator={() => setOperatorDialogOpen(true)}
                operatorSecret={operatorSecret}
              />
            ) : null
          ) : loadingCases ? (
            <LoadingPanel label="Loading merchant dispute queue…" />
          ) : activeView === "overview" ? (
            <Overview
              cases={cases}
              onOpenCase={openCase}
              onOpenQueue={() => setActiveView("cases")}
            />
          ) : (
            <CaseQueue cases={cases} onOpenCase={openCase} />
          )}
        </main>
      </div>

      <OperatorAccessDialog
        onClose={() => setOperatorDialogOpen(false)}
        onUnlock={(secret) => {
          setOperatorSecret(secret);
          setOperatorDialogOpen(false);
          notify("Operator controls unlocked for this session.", "good");
        }}
        open={operatorDialogOpen}
      />

      {toast ? (
        <div aria-live="polite" className={`toast toast-${toast.tone}`} role="status">
          <Icon name={toast.tone === "good" ? "check" : "warning"} size={18} />
          {toast.message}
        </div>
      ) : null}
    </div>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div aria-busy="true" className="loading-panel">
      <span className="loading-mark"><Icon name="shield" size={30} /></span>
      <strong>{label}</strong>
      <div className="loading-line"><span /></div>
    </div>
  );
}

function ErrorPanel({
  error,
  loading,
  onRetry,
}: {
  error: string;
  loading: boolean;
  onRetry: () => void;
}) {
  return (
    <section className="error-panel">
      <span><Icon name="warning" size={30} /></span>
      <p className="eyebrow">Connection required</p>
      <h1>The local ProofShield API is not ready</h1>
      <p>{error}</p>
      <code>Start FastAPI on http://127.0.0.1:8000 with your backend-only Supabase environment.</code>
      <button className="primary-button" disabled={loading} onClick={onRetry} type="button">
        <Icon name="refresh" size={17} /> {loading ? "Checking…" : "Retry connection"}
      </button>
    </section>
  );
}
