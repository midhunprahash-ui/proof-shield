import { useEffect, useState } from "react";

import { ApiError, type ProofShieldApi } from "../api";
import { decisionLabel, formatDateTime, shortId } from "../lib/format";
import type { DraftReview, ResponseDraft, ReviewDecision } from "../types";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export function ResponsePanel({
  api,
  disputeId,
  drafts,
  notify,
  onChanged,
  onRequestOperator,
  operatorSecret,
}: {
  api: ProofShieldApi;
  disputeId: string;
  drafts: ResponseDraft[];
  notify: (message: string, tone?: "danger" | "good") => void;
  onChanged: () => Promise<void>;
  onRequestOperator: () => void;
  operatorSecret: string;
}) {
  const draft = drafts[0] ?? null;
  const [review, setReview] = useState<DraftReview | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [reviewing, setReviewing] = useState<ReviewDecision | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [reviewerLabel, setReviewerLabel] = useState("");
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!draft || !operatorSecret) {
      setReview(null);
      return;
    }
    const controller = new AbortController();
    setReviewLoading(true);
    api
      .getReview(disputeId, draft.draft_id, operatorSecret, controller.signal)
      .then((saved) => {
        if (!controller.signal.aborted) setReview(saved);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setReview(null);
          return;
        }
        notify(error instanceof Error ? error.message : "Review could not be loaded.", "danger");
      })
      .finally(() => {
        if (!controller.signal.aborted) setReviewLoading(false);
      });
    return () => controller.abort();
  }, [api, disputeId, draft, notify, operatorSecret]);

  async function createDraft() {
    setCreating(true);
    try {
      await api.createDraft(disputeId);
      notify("Evidence-grounded response draft created.", "good");
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Draft could not be created.", "danger");
    } finally {
      setCreating(false);
    }
  }

  async function decide(decision: ReviewDecision) {
    if (!draft) return;
    if (!operatorSecret) {
      onRequestOperator();
      return;
    }
    if (!reviewerLabel.trim()) {
      notify("Add a reviewer label before recording the decision.", "danger");
      return;
    }
    setReviewing(decision);
    try {
      const saved = await api.reviewDraft(
        disputeId,
        draft.draft_id,
        {
          decision,
          reviewerLabel: reviewerLabel.trim(),
          ...(note.trim() ? { note: note.trim() } : {}),
        },
        operatorSecret,
      );
      setReview(saved);
      notify(`Draft ${decision.toLowerCase()} and sealed in the audit record.`, "good");
      await onChanged();
    } catch (error) {
      notify(error instanceof Error ? error.message : "Review could not be recorded.", "danger");
    } finally {
      setReviewing(null);
    }
  }

  async function downloadPacket() {
    if (!draft || !operatorSecret) {
      onRequestOperator();
      return;
    }
    setDownloading(true);
    try {
      const packet = await api.downloadPacket(disputeId, draft.draft_id, operatorSecret);
      const url = URL.createObjectURL(packet.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `proofshield-${disputeId}-evidence-packet.zip`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      notify(`Packet downloaded · SHA-256 ${shortId(packet.packetSha256, 7)}`, "good");
    } catch (error) {
      notify(error instanceof Error ? error.message : "Packet could not be downloaded.", "danger");
    } finally {
      setDownloading(false);
    }
  }

  if (!draft) {
    return (
      <section className="detail-card response-empty">
        <span><Icon name="file" size={30} /></span>
        <p className="eyebrow">Evidence-grounded drafting</p>
        <h3>No response draft yet</h3>
        <p>
          ProofShield will draft only when the verifier finds complete, consistent,
          human-reviewed evidence with source hashes.
        </p>
        <button className="primary-button" disabled={creating} onClick={() => void createDraft()} type="button">
          {creating ? "Checking evidence…" : "Verify and create draft"}
        </button>
      </section>
    );
  }

  return (
    <div className="panel-stack">
      <section className="workspace-grid response-grid">
        <article className="detail-card span-two response-document">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Pending human approval</p>
              <h3>{draft.subject}</h3>
            </div>
            <StatusBadge tone="blue">{decisionLabel(draft.decision)}</StatusBadge>
          </div>
          <div className="draft-body">{draft.body}</div>
          <div className="draft-meta">
            <span>Generated {formatDateTime(draft.created_at)}</span>
            <code>SHA-256 {shortId(draft.content_sha256, 9)}</code>
          </div>
        </article>

        <article className="detail-card citation-card">
          <div className="card-heading">
            <div>
              <p className="eyebrow">Traceable claims</p>
              <h3>Citations</h3>
            </div>
            <span className="card-count">{draft.citations.length}</span>
          </div>
          <div className="citation-list">
            {draft.citations.map((citation) => (
              <div className="citation-item" key={`${citation.evidence_id}-${citation.label}`}>
                <span><Icon name="check" size={15} /></span>
                <div>
                  <strong>{citation.label}</strong>
                  <p>{citation.claim}</p>
                  <small>{citation.source_name} · {shortId(citation.source_sha256, 6)}</small>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="detail-card review-card">
        <div className="card-heading">
          <div>
            <p className="eyebrow">Final control gate</p>
            <h3>Human review</h3>
          </div>
          {review ? (
            <StatusBadge tone={review.decision === "APPROVED" ? "good" : "danger"}>
              {review.decision === "APPROVED" ? "Approved" : "Rejected"}
            </StatusBadge>
          ) : (
            <StatusBadge tone="warning">Awaiting decision</StatusBadge>
          )}
        </div>

        {reviewLoading ? <p className="muted-copy">Loading protected review…</p> : null}
        {review ? (
          <div className="sealed-review">
            <span className={review.decision === "APPROVED" ? "review-seal approved" : "review-seal rejected"}>
              <Icon name={review.decision === "APPROVED" ? "check" : "x"} size={26} />
            </span>
            <div>
              <strong>Decision recorded by {review.reviewer_label}</strong>
              <p>{review.note || "No reviewer note was added."}</p>
              <small>{formatDateTime(review.created_at)} · immutable after submission</small>
            </div>
            {review.decision === "APPROVED" ? (
              <button className="primary-button" disabled={downloading} onClick={() => void downloadPacket()} type="button">
                <Icon name="download" size={17} />
                {downloading ? "Building packet…" : "Download evidence packet"}
              </button>
            ) : null}
          </div>
        ) : (
          <div className="review-form">
            {!operatorSecret ? (
              <button className="access-banner" onClick={onRequestOperator} type="button">
                <span><Icon name="lock" size={18} /></span>
                <div>
                  <strong>Operator access required</strong>
                  <small>Unlock protected approval controls for this session.</small>
                </div>
                <Icon name="chevron" size={17} />
              </button>
            ) : null}
            <div className="form-grid">
              <label>
                Reviewer label
                <input
                  disabled={!operatorSecret}
                  onChange={(event) => setReviewerLabel(event.target.value)}
                  placeholder="e.g. Merchant risk lead"
                  value={reviewerLabel}
                />
              </label>
              <label>
                Decision note <span>(optional)</span>
                <input
                  disabled={!operatorSecret}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="Why is this response safe or unsafe?"
                  value={note}
                />
              </label>
            </div>
            <div className="review-actions">
              <p><Icon name="lock" size={15} /> A decision is permanent and append-only.</p>
              <div>
                <button
                  className="secondary-button danger-button"
                  disabled={reviewing !== null || !operatorSecret}
                  onClick={() => void decide("REJECTED")}
                  type="button"
                >
                  {reviewing === "REJECTED" ? "Recording…" : "Reject draft"}
                </button>
                <button
                  className="primary-button"
                  disabled={reviewing !== null || !operatorSecret}
                  onClick={() => void decide("APPROVED")}
                  type="button"
                >
                  <Icon name="check" size={17} />
                  {reviewing === "APPROVED" ? "Recording…" : "Approve response"}
                </button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
