import { useMemo, useState } from "react";

import type { ProofShieldApi } from "../api";
import { evidenceTypeLabel, formatDateTime, shortId } from "../lib/format";
import type {
  DisputeCase,
  EvidenceResolution,
  EvidenceResolutionAction,
} from "../types";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export function EvidenceResolutionPanel({
  api,
  caseData,
  notify,
  onChanged,
  resolutions,
}: {
  api: ProofShieldApi;
  caseData: DisputeCase;
  notify: (message: string, tone?: "danger" | "good") => void;
  onChanged: () => Promise<void>;
  resolutions: EvidenceResolution[];
}) {
  const [evidenceId, setEvidenceId] = useState("");
  const [action, setAction] = useState<EvidenceResolutionAction>(
    "EXCLUDED_INCORRECT",
  );
  const [replacementEvidenceId, setReplacementEvidenceId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);

  const resolvedIds = useMemo(
    () => new Set(resolutions.map((resolution) => resolution.evidence_id)),
    [resolutions],
  );
  const protectedReplacementIds = useMemo(
    () => new Set(
      resolutions.flatMap((resolution) =>
        resolution.replacement_evidence_id
          ? [resolution.replacement_evidence_id]
          : [],
      ),
    ),
    [resolutions],
  );
  const activeEvidence = caseData.evidence.filter(
    (evidence) =>
      !resolvedIds.has(evidence.evidence_id)
      && !protectedReplacementIds.has(evidence.evidence_id),
  );
  const selectedEvidence = activeEvidence.find(
    (evidence) => evidence.evidence_id === evidenceId,
  );
  const replacementOptions = selectedEvidence
    ? caseData.evidence.filter(
      (evidence) =>
        evidence.evidence_id !== selectedEvidence.evidence_id
        && evidence.evidence_type === selectedEvidence.evidence_type
        && !resolvedIds.has(evidence.evidence_id),
    )
    : [];
  const canSubmit = Boolean(
    selectedEvidence
    && confirmed
    && reason.trim().length >= 10
    && (action === "EXCLUDED_INCORRECT" || replacementEvidenceId),
  );

  async function resolveEvidence() {
    if (!canSubmit) return;
    setSaving(true);
    try {
      await api.resolveEvidence(caseData.dispute_id, {
        evidence_id: evidenceId,
        action,
        ...(action === "SUPERSEDED"
          ? { replacement_evidence_id: replacementEvidenceId }
          : {}),
        reason: reason.trim(),
      });
      notify("Evidence resolution recorded without changing the original record.", "good");
      setEvidenceId("");
      setReplacementEvidenceId("");
      setReason("");
      setConfirmed(false);
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Resolution could not be saved.", "danger");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="detail-card resolution-card">
      <div className="card-heading">
        <div>
          <p className="eyebrow">Append-only correction</p>
          <h3>Resolve incorrect or superseded evidence</h3>
        </div>
        <StatusBadge tone={resolutions.length > 0 ? "warning" : "muted"}>
          {resolutions.length} resolutions
        </StatusBadge>
      </div>
      <p className="muted-copy">
        The original record and source file remain in the audit trail. A resolution only
        excludes that record from future checks, drafts, approvals and packet exports.
      </p>

      {resolutions.length > 0 ? (
        <div className="resolution-list">
          {resolutions.map((resolution) => (
            <article key={resolution.resolution_id}>
              <span><Icon name="warning" size={16} /></span>
              <div>
                <strong>{shortId(resolution.evidence_id)}</strong>
                <small>
                  {resolution.action === "SUPERSEDED"
                    ? `Superseded by ${shortId(resolution.replacement_evidence_id ?? "")}`
                    : "Excluded as incorrect"}
                  {` · ${formatDateTime(resolution.created_at)}`}
                </small>
                <p>{resolution.reason}</p>
              </div>
            </article>
          ))}
        </div>
      ) : null}

      <div className="form-grid resolution-form">
        <label>
          Evidence to resolve
          <select
            onChange={(event) => {
              setEvidenceId(event.target.value);
              setReplacementEvidenceId("");
              setConfirmed(false);
            }}
            value={evidenceId}
          >
            <option value="">Select an active evidence record</option>
            {activeEvidence.map((evidence) => (
              <option key={evidence.evidence_id} value={evidence.evidence_id}>
                {evidenceTypeLabel(evidence.evidence_type)} · {shortId(evidence.evidence_id)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Resolution action
          <select
            onChange={(event) => {
              setAction(event.target.value as EvidenceResolutionAction);
              setReplacementEvidenceId("");
              setConfirmed(false);
            }}
            value={action}
          >
            <option value="EXCLUDED_INCORRECT">Exclude as incorrect</option>
            <option value="SUPERSEDED">Supersede with a replacement</option>
          </select>
        </label>
        {action === "SUPERSEDED" ? (
          <label>
            Same-type replacement
            <select
              disabled={!selectedEvidence}
              onChange={(event) => {
                setReplacementEvidenceId(event.target.value);
                setConfirmed(false);
              }}
              value={replacementEvidenceId}
            >
              <option value="">Select replacement evidence</option>
              {replacementOptions.map((evidence) => (
                <option key={evidence.evidence_id} value={evidence.evidence_id}>
                  {evidenceTypeLabel(evidence.evidence_type)} · {shortId(evidence.evidence_id)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <label className="span-two-field">
          Required reason
          <textarea
            maxLength={2000}
            minLength={10}
            onChange={(event) => {
              setReason(event.target.value);
              setConfirmed(false);
            }}
            placeholder="Describe what was checked and why this evidence must no longer influence the case."
            rows={3}
            value={reason}
          />
        </label>
        <label className="check-field confirmation-field span-two-field">
          <input
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            type="checkbox"
          />
          I understand this resolution is permanent and the original evidence stays visible
        </label>
      </div>
      <div className="form-actions">
        <span>Drafts created before this action become stale and require reassessment.</span>
        <button
          className="danger-button"
          disabled={!canSubmit || saving}
          onClick={() => void resolveEvidence()}
          type="button"
        >
          {saving ? "Recording resolution…" : "Record permanent resolution"}
        </button>
      </div>
    </section>
  );
}
