"""In-memory adapters used by deterministic unit tests and local demos."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from threading import RLock

from proofshield.audit import AuditEntry, AuditStatus, ClaimResult
from proofshield.case_store import (
    CaseConflictError,
    CaseHistoryAction,
    CaseHistoryEntry,
    CaseNotFoundError,
    CaseSummary,
    DraftConflictError,
    DraftNotFoundError,
    EvidenceConflictError,
    EvidenceFileMetadata,
    EvidenceFileRecord,
    EvidenceResolutionConflictError,
    ReviewConflictError,
    ReviewNotFoundError,
    model_sha256,
)
from proofshield.domain import Assessment, Decision, DisputeCase, EvidenceDocument
from proofshield.drafting import ResponseDraft
from proofshield.file_store import (
    EvidenceFileUnavailable,
    StoredFileBlob,
    normalize_and_validate_file,
)
from proofshield.resolution import EvidenceResolution
from proofshield.reviewing import DraftReview, ReviewDecision


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._cases: dict[str, tuple[DisputeCase, str, datetime]] = {}
        self._owners: dict[str, str | None] = {}
        self._evidence: dict[str, tuple[str, EvidenceDocument, str, datetime]] = {}
        self._resolutions: dict[str, EvidenceResolution] = {}
        self._files: dict[str, tuple[EvidenceFileMetadata, str]] = {}
        self._drafts: dict[str, ResponseDraft] = {}
        self._reviews: dict[str, DraftReview] = {}
        self._history: list[CaseHistoryEntry] = []
        self._sequence = 0

    def save_case(
        self, case: DisputeCase, *, source: str, owner_id: str | None = None
    ) -> bool:
        core_case = case.model_copy(update={"evidence": []})
        digest = model_sha256(core_case)
        with self._lock:
            existing = self._cases.get(case.dispute_id)
            if existing is not None:
                if existing[1] != digest:
                    raise CaseConflictError(
                        f"case {case.dispute_id} already exists with different core facts"
                    )
                if self._owners[case.dispute_id] != owner_id:
                    raise CaseConflictError(
                        f"case {case.dispute_id} already has a different owner"
                    )
                return False
            now = datetime.now(UTC)
            self._cases[case.dispute_id] = (core_case, digest, now)
            self._owners[case.dispute_id] = owner_id
            self._append_history(
                case.dispute_id,
                CaseHistoryAction.CASE_CREATED,
                None,
                f"Case created from {source}.",
                now,
            )
        return True

    def get_case(self, dispute_id: str) -> DisputeCase:
        with self._lock:
            stored = self._cases.get(dispute_id)
            if stored is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            evidence = [
                row[1]
                for row in sorted(
                    self._evidence.values(), key=lambda row: (row[3], row[1].evidence_id)
                )
                if row[0] == dispute_id
            ]
            return stored[0].model_copy(update={"evidence": evidence}, deep=True)

    def list_cases(self, *, owner_id: str | None = None) -> list[CaseSummary]:
        with self._lock:
            rows = []
            for dispute_id, (case, _digest, updated_at) in self._cases.items():
                if owner_id is not None and self._owners[dispute_id] != owner_id:
                    continue
                rows.append(
                    CaseSummary(
                        dispute_id=dispute_id,
                        payment_id=case.payment_id,
                        order_id=case.order_id,
                        reason=case.reason,
                        disputed_amount=str(case.disputed_amount),
                        currency=case.currency,
                        evidence_count=sum(
                            1 for row in self._evidence.values() if row[0] == dispute_id
                        ),
                        updated_at=updated_at,
                    )
                )
            return sorted(rows, key=lambda row: (row.updated_at, row.dispute_id), reverse=True)

    def list_unassigned_cases(self) -> list[CaseSummary]:
        with self._lock:
            rows = []
            for dispute_id, (case, _digest, updated_at) in self._cases.items():
                if self._owners[dispute_id] is not None:
                    continue
                rows.append(
                    CaseSummary(
                        dispute_id=dispute_id,
                        payment_id=case.payment_id,
                        order_id=case.order_id,
                        reason=case.reason,
                        disputed_amount=str(case.disputed_amount),
                        currency=case.currency,
                        evidence_count=sum(
                            1 for row in self._evidence.values() if row[0] == dispute_id
                        ),
                        updated_at=updated_at,
                    )
                )
            return sorted(rows, key=lambda row: (row.updated_at, row.dispute_id), reverse=True)

    def claim_case(self, dispute_id: str, owner_id: str) -> bool:
        with self._lock:
            stored = self._cases.get(dispute_id)
            if stored is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            current_owner = self._owners[dispute_id]
            if current_owner == owner_id:
                return False
            if current_owner is not None:
                raise CaseConflictError(
                    f"case {dispute_id} was claimed by another operator"
                )
            now = datetime.now(UTC)
            self._owners[dispute_id] = owner_id
            self._cases[dispute_id] = (stored[0], stored[1], now)
            self._append_history(
                dispute_id,
                CaseHistoryAction.CASE_CLAIMED,
                owner_id,
                "Case claimed by an authenticated operator.",
                now,
            )
            return True

    def require_case_owner(self, dispute_id: str, owner_id: str) -> None:
        with self._lock:
            if self._owners.get(dispute_id) != owner_id:
                raise CaseNotFoundError(f"case {dispute_id} was not found")

    def register_evidence_file(
        self,
        dispute_id: str,
        *,
        file_id: str,
        original_name: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
    ) -> EvidenceFileMetadata:
        with self._lock:
            self._require_case(dispute_id)
            if file_id in self._files:
                raise EvidenceConflictError(f"evidence file {file_id} could not be registered")
            now = datetime.now(UTC)
            metadata = EvidenceFileMetadata(
                file_id=file_id,
                dispute_id=dispute_id,
                original_name=original_name,
                content_type=content_type,
                size_bytes=size_bytes,
                sha256=sha256,
                created_at=now,
            )
            self._files[file_id] = (metadata, storage_key)
            case, digest, _updated = self._cases[dispute_id]
            self._cases[dispute_id] = (case, digest, now)
            self._append_history(
                dispute_id,
                CaseHistoryAction.FILE_UPLOADED,
                file_id,
                (
                    f"Evidence file uploaded; content_type={content_type}; "
                    f"size_bytes={size_bytes}."
                ),
                now,
            )
            return metadata.model_copy(deep=True)

    def get_evidence_file(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileMetadata:
        return self.get_evidence_file_record(dispute_id, file_id).metadata

    def get_evidence_file_record(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileRecord:
        with self._lock:
            row = self._files.get(file_id)
            if row is None or row[0].dispute_id != dispute_id:
                raise CaseNotFoundError(
                    f"evidence file {file_id} was not found for case {dispute_id}"
                )
            return EvidenceFileRecord(
                metadata=row[0].model_copy(deep=True),
                storage_key=row[1],
            )

    def list_evidence_files(self, dispute_id: str) -> list[EvidenceFileMetadata]:
        with self._lock:
            self._require_case(dispute_id)
            rows = [
                row[0].model_copy(deep=True)
                for row in self._files.values()
                if row[0].dispute_id == dispute_id
            ]
            return sorted(rows, key=lambda row: (row.created_at, row.file_id))

    def add_evidence(self, dispute_id: str, document: EvidenceDocument) -> bool:
        digest = model_sha256(document)
        with self._lock:
            self._require_case(dispute_id)
            existing = self._evidence.get(document.evidence_id)
            if existing is not None:
                if existing[0] == dispute_id and existing[2] == digest:
                    return False
                raise EvidenceConflictError(
                    f"evidence ID {document.evidence_id} is already attached elsewhere"
                )
            now = datetime.now(UTC)
            self._evidence[document.evidence_id] = (
                dispute_id,
                document.model_copy(deep=True),
                digest,
                now,
            )
            case, case_digest, _updated = self._cases[dispute_id]
            self._cases[dispute_id] = (case, case_digest, now)
            self._append_history(
                dispute_id,
                CaseHistoryAction.EVIDENCE_ADDED,
                document.evidence_id,
                (
                    f"{document.evidence_type} evidence added; "
                    f"source_verified={document.source_verified}."
                ),
                now,
            )
        return True

    def save_evidence_resolution(self, resolution: EvidenceResolution) -> bool:
        with self._lock:
            self._require_case(resolution.dispute_id)
            existing = self._resolutions.get(resolution.evidence_id)
            if existing is not None:
                if existing.request_sha256 == resolution.request_sha256:
                    return False
                raise EvidenceResolutionConflictError(
                    f"evidence {resolution.evidence_id} already has a resolution"
                )
            now = resolution.created_at
            self._resolutions[resolution.evidence_id] = resolution.model_copy(deep=True)
            case, digest, _updated = self._cases[resolution.dispute_id]
            self._cases[resolution.dispute_id] = (case, digest, now)
            self._append_history(
                resolution.dispute_id,
                CaseHistoryAction.EVIDENCE_RESOLVED,
                resolution.resolution_id,
                (
                    f"Evidence {resolution.evidence_id}; action={resolution.action}; "
                    f"replacement={resolution.replacement_evidence_id or 'none'}."
                ),
                now,
            )
            return True

    def get_evidence_resolution(
        self, dispute_id: str, evidence_id: str
    ) -> EvidenceResolution:
        with self._lock:
            self._require_case(dispute_id)
            resolution = self._resolutions.get(evidence_id)
            if resolution is None or resolution.dispute_id != dispute_id:
                raise CaseNotFoundError(
                    f"evidence {evidence_id} has no resolution for case {dispute_id}"
                )
            return resolution.model_copy(deep=True)

    def list_evidence_resolutions(
        self, dispute_id: str
    ) -> list[EvidenceResolution]:
        with self._lock:
            self._require_case(dispute_id)
            return sorted(
                (
                    resolution.model_copy(deep=True)
                    for resolution in self._resolutions.values()
                    if resolution.dispute_id == dispute_id
                ),
                key=lambda item: (item.created_at, item.resolution_id),
            )

    def record_assessment(self, assessment: Assessment) -> None:
        with self._lock:
            self._require_case(assessment.dispute_id)
            now = datetime.now(UTC)
            self._append_history(
                assessment.dispute_id,
                CaseHistoryAction.ASSESSED,
                None,
                (
                    f"Decision={assessment.decision}; "
                    f"evidence_score={assessment.evidence_score:.4f}."
                ),
                now,
            )

    def save_draft(self, draft: ResponseDraft) -> bool:
        with self._lock:
            self._require_case(draft.dispute_id)
            existing = self._drafts.get(draft.draft_id)
            if existing is not None:
                if (
                    existing.dispute_id == draft.dispute_id
                    and existing.input_sha256 == draft.input_sha256
                    and existing.content_sha256 == draft.content_sha256
                ):
                    return False
                raise DraftConflictError(
                    f"draft {draft.draft_id} already exists with different content"
                )
            self._drafts[draft.draft_id] = draft.model_copy(deep=True)
            case, digest, _updated = self._cases[draft.dispute_id]
            self._cases[draft.dispute_id] = (case, digest, draft.created_at)
            self._append_history(
                draft.dispute_id,
                CaseHistoryAction.DRAFT_CREATED,
                draft.draft_id,
                (
                    f"Draft created; generator={draft.generator}; "
                    f"status={draft.status}; decision={draft.decision}."
                ),
                draft.created_at,
            )
            return True

    def get_draft(self, dispute_id: str, draft_id: str) -> ResponseDraft:
        with self._lock:
            self._require_case(dispute_id)
            draft = self._drafts.get(draft_id)
            if draft is None or draft.dispute_id != dispute_id:
                raise DraftNotFoundError(
                    f"draft {draft_id} was not found for case {dispute_id}"
                )
            return draft.model_copy(deep=True)

    def list_drafts(self, dispute_id: str) -> list[ResponseDraft]:
        with self._lock:
            self._require_case(dispute_id)
            rows = [
                draft.model_copy(deep=True)
                for draft in self._drafts.values()
                if draft.dispute_id == dispute_id
            ]
            return sorted(
                rows,
                key=lambda draft: (draft.created_at, draft.draft_id),
                reverse=True,
            )

    def save_review(self, review: DraftReview) -> bool:
        with self._lock:
            draft = self._drafts.get(review.draft_id)
            if draft is None or draft.dispute_id != review.dispute_id:
                raise DraftNotFoundError(
                    f"draft {review.draft_id} was not found for case {review.dispute_id}"
                )
            existing = self._reviews.get(review.draft_id)
            if existing is not None:
                if existing.request_sha256 == review.request_sha256:
                    return False
                raise ReviewConflictError(
                    f"draft {review.draft_id} already has a different final review"
                )
            self._reviews[review.draft_id] = review.model_copy(deep=True)
            case, digest, _updated = self._cases[review.dispute_id]
            self._cases[review.dispute_id] = (case, digest, review.created_at)
            action = (
                CaseHistoryAction.DRAFT_APPROVED
                if review.decision == ReviewDecision.APPROVED
                else CaseHistoryAction.DRAFT_REJECTED
            )
            self._append_history(
                review.dispute_id,
                action,
                review.review_id,
                (
                    f"Draft {review.decision.value.lower()}; "
                    f"reviewer_label={review.reviewer_label}."
                ),
                review.created_at,
            )
            return True

    def get_review(self, dispute_id: str, draft_id: str) -> DraftReview:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None or draft.dispute_id != dispute_id:
                raise DraftNotFoundError(
                    f"draft {draft_id} was not found for case {dispute_id}"
                )
            review = self._reviews.get(draft_id)
            if review is None:
                raise ReviewNotFoundError(f"draft {draft_id} has not been reviewed")
            return review.model_copy(deep=True)

    def get_history(self, dispute_id: str) -> list[CaseHistoryEntry]:
        with self._lock:
            self._require_case(dispute_id)
            return [
                entry.model_copy(deep=True)
                for entry in self._history
                if entry.dispute_id == dispute_id
            ]

    def _require_case(self, dispute_id: str) -> None:
        if dispute_id not in self._cases:
            raise CaseNotFoundError(f"case {dispute_id} was not found")

    def _append_history(
        self,
        dispute_id: str,
        action: CaseHistoryAction,
        reference_id: str | None,
        detail: str,
        recorded_at: datetime,
    ) -> None:
        self._sequence += 1
        self._history.append(
            CaseHistoryEntry(
                sequence=self._sequence,
                dispute_id=dispute_id,
                action=action,
                reference_id=reference_id,
                recorded_at=recorded_at,
                detail=detail,
            )
        )


class InMemoryEvidenceFileStore:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def save(
        self,
        content: bytes,
        *,
        content_type: str | None,
        dispute_id: str,
        file_id: str,
    ) -> StoredFileBlob:
        _normalized, digest = normalize_and_validate_file(content, content_type)
        case_key = hashlib.sha256(dispute_id.encode("utf-8")).hexdigest()
        storage_key = f"cases/{case_key}/{file_id}/{digest}"
        self.blobs[storage_key] = content
        return StoredFileBlob(
            storage_key=storage_key,
            sha256=digest,
            size_bytes=len(content),
        )

    def delete(self, storage_key: str) -> None:
        self.blobs.pop(storage_key, None)

    def read(self, storage_key: str) -> bytes:
        try:
            return self.blobs[storage_key]
        except KeyError as error:
            raise EvidenceFileUnavailable(
                "a cited evidence file could not be read from private storage"
            ) from error


class InMemoryEventLedger:
    def __init__(self) -> None:
        self._lock = RLock()
        self._completed: dict[str, str] = {}
        self._active: dict[str, str] = {}
        self._entries: list[AuditEntry] = []

    def claim(self, event_id: str, digest: str, *, event_type: str | None) -> ClaimResult:
        with self._lock:
            existing_digest = self._completed.get(event_id) or self._active.get(event_id)
            if existing_digest is not None:
                status = (
                    AuditStatus.DUPLICATE
                    if existing_digest == digest
                    else AuditStatus.REJECTED
                )
                self._append(
                    event_id,
                    digest,
                    status,
                    event_type=event_type,
                    detail=(
                        "Duplicate event was acknowledged without reprocessing."
                        if status == AuditStatus.DUPLICATE
                        else "Event ID was reused with a different signed body."
                    ),
                )
                return (
                    ClaimResult.DUPLICATE
                    if status == AuditStatus.DUPLICATE
                    else ClaimResult.CONFLICT
                )
            self._active[event_id] = digest
            self._append(
                event_id,
                digest,
                AuditStatus.RECEIVED,
                event_type=event_type,
                detail="Signature verified and event accepted for processing.",
            )
            return ClaimResult.CLAIMED

    def finish(
        self,
        event_id: str,
        digest: str,
        *,
        status: AuditStatus,
        detail: str,
        event_type: str | None = None,
        dispute_id: str | None = None,
        decision: Decision | None = None,
    ) -> None:
        if status not in {
            AuditStatus.PROCESSED,
            AuditStatus.IGNORED,
            AuditStatus.NEEDS_ENRICHMENT,
        }:
            raise ValueError("finish status must describe a completed event")
        with self._lock:
            if self._active.get(event_id) != digest:
                raise ValueError("event was not claimed with this body digest")
            self._active.pop(event_id)
            self._completed[event_id] = digest
            self._append(
                event_id,
                digest,
                status,
                event_type=event_type,
                dispute_id=dispute_id,
                decision=decision,
                detail=detail,
            )

    def fail(
        self,
        event_id: str,
        digest: str,
        *,
        detail: str,
        event_type: str | None = None,
    ) -> None:
        with self._lock:
            self._active.pop(event_id, None)
            self._append(
                event_id,
                digest,
                AuditStatus.FAILED,
                event_type=event_type,
                detail=detail,
            )

    def reject_untrusted(self, event_id: str, digest: str, *, detail: str) -> None:
        with self._lock:
            self._append(event_id, digest, AuditStatus.REJECTED, detail=detail)

    def entries(self) -> list[AuditEntry]:
        with self._lock:
            return [entry.model_copy(deep=True) for entry in self._entries]

    def _append(
        self,
        event_id: str,
        digest: str,
        status: AuditStatus,
        *,
        detail: str,
        event_type: str | None = None,
        dispute_id: str | None = None,
        decision: Decision | None = None,
    ) -> None:
        self._entries.append(
            AuditEntry(
                event_id=event_id,
                body_sha256=digest,
                status=status,
                recorded_at=datetime.now(UTC),
                event_type=event_type,
                dispute_id=dispute_id,
                decision=decision,
                detail=detail,
            )
        )
