"""Case persistence contracts and the Supabase-backed repository."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel

from proofshield.domain import Assessment, DisputeCase, EvidenceDocument
from proofshield.drafting import ResponseDraft
from proofshield.reviewing import DraftReview


class CaseStoreError(RuntimeError):
    """Base class for case-storage errors."""


class CaseNotFoundError(CaseStoreError):
    pass


class CaseConflictError(CaseStoreError):
    pass


class EvidenceConflictError(CaseStoreError):
    pass


class DraftConflictError(CaseStoreError):
    pass


class DraftNotFoundError(CaseStoreError):
    pass


class ReviewConflictError(CaseStoreError):
    pass


class ReviewNotFoundError(CaseStoreError):
    pass


class CaseHistoryAction(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    CASE_CLAIMED = "CASE_CLAIMED"
    FILE_UPLOADED = "FILE_UPLOADED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    ASSESSED = "ASSESSED"
    DRAFT_CREATED = "DRAFT_CREATED"
    DRAFT_APPROVED = "DRAFT_APPROVED"
    DRAFT_REJECTED = "DRAFT_REJECTED"


class CaseSummary(BaseModel):
    dispute_id: str
    payment_id: str
    order_id: str
    reason: str
    disputed_amount: str
    currency: str
    evidence_count: int
    updated_at: AwareDatetime


class CaseHistoryEntry(BaseModel):
    sequence: int
    dispute_id: str
    action: CaseHistoryAction
    reference_id: str | None
    recorded_at: AwareDatetime
    detail: str


class EvidenceFileMetadata(BaseModel):
    file_id: str
    dispute_id: str
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: AwareDatetime


class EvidenceFileRecord(BaseModel):
    metadata: EvidenceFileMetadata
    storage_key: str


class CaseRepository(Protocol):
    def save_case(
        self, case: DisputeCase, *, source: str, owner_id: str | None = None
    ) -> bool: ...

    def get_case(self, dispute_id: str) -> DisputeCase: ...

    def list_cases(self, *, owner_id: str | None = None) -> list[CaseSummary]: ...

    def list_unassigned_cases(self) -> list[CaseSummary]: ...

    def claim_case(self, dispute_id: str, owner_id: str) -> bool: ...

    def require_case_owner(self, dispute_id: str, owner_id: str) -> None: ...

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
    ) -> EvidenceFileMetadata: ...

    def get_evidence_file(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileMetadata: ...

    def get_evidence_file_record(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileRecord: ...

    def list_evidence_files(self, dispute_id: str) -> list[EvidenceFileMetadata]: ...

    def add_evidence(self, dispute_id: str, document: EvidenceDocument) -> bool: ...

    def record_assessment(self, assessment: Assessment) -> None: ...

    def save_draft(self, draft: ResponseDraft) -> bool: ...

    def get_draft(self, dispute_id: str, draft_id: str) -> ResponseDraft: ...

    def list_drafts(self, dispute_id: str) -> list[ResponseDraft]: ...

    def save_review(self, review: DraftReview) -> bool: ...

    def get_review(self, dispute_id: str, draft_id: str) -> DraftReview: ...

    def get_history(self, dispute_id: str) -> list[CaseHistoryEntry]: ...


def canonical_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def model_sha256(model: BaseModel) -> str:
    return hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()


def new_file_id() -> str:
    return f"file_{uuid4().hex}"


def _rpc_status(client: Any, function: str, parameters: dict[str, Any]) -> str:
    data = client.rpc(function, parameters).execute().data
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        value = data.get(function) or data.get("status")
        if isinstance(value, str):
            return value
    if isinstance(data, list) and len(data) == 1:
        item = data[0]
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            value = item.get(function) or item.get("status")
            if isinstance(value, str):
                return value
    raise CaseStoreError(f"Supabase RPC {function} returned an unexpected response")


class SupabaseCaseRepository:
    """Store trusted case facts through transaction-safe Postgres RPCs."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def save_case(
        self, case: DisputeCase, *, source: str, owner_id: str | None = None
    ) -> bool:
        core_case = case.model_copy(update={"evidence": []})
        result = _rpc_status(
            self.client,
            "proofshield_save_case",
            {
                "p_dispute_id": case.dispute_id,
                "p_payment_id": case.payment_id,
                "p_order_id": case.order_id,
                "p_reason": case.reason,
                "p_disputed_amount": str(case.disputed_amount),
                "p_currency": case.currency,
                "p_core_json": core_case.model_dump(mode="json"),
                "p_core_sha256": model_sha256(core_case),
                "p_source": source,
                "p_owner_id": owner_id,
            },
        )
        if result == "CREATED":
            return True
        if result == "EXISTS":
            return False
        if result == "CONFLICT":
            raise CaseConflictError(
                f"case {case.dispute_id} already exists with different core facts"
            )
        if result in {"OWNER_CONFLICT", "OWNER_NOT_AUTHORIZED"}:
            raise CaseConflictError(
                f"case {case.dispute_id} could not be assigned to this operator"
            )
        raise CaseStoreError(f"unexpected save-case status: {result}")

    def get_case(self, dispute_id: str) -> DisputeCase:
        rows = (
            self.client.table("proofshield_cases")
            .select("core_json")
            .eq("dispute_id", dispute_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise CaseNotFoundError(f"case {dispute_id} was not found")
        evidence_rows = (
            self.client.table("proofshield_evidence")
            .select("document_json")
            .eq("dispute_id", dispute_id)
            .order("created_at")
            .order("evidence_id")
            .execute()
            .data
        )
        case = DisputeCase.model_validate(rows[0]["core_json"])
        evidence = [
            EvidenceDocument.model_validate(row["document_json"])
            for row in evidence_rows
        ]
        return case.model_copy(update={"evidence": evidence})

    def list_cases(self, *, owner_id: str | None = None) -> list[CaseSummary]:
        data = (
            self.client.rpc("proofshield_list_cases", {"p_owner_id": owner_id})
            .execute()
            .data
        )
        if not isinstance(data, list):
            raise CaseStoreError("Supabase list-cases RPC returned an unexpected response")
        return [CaseSummary.model_validate(row) for row in data]

    def list_unassigned_cases(self) -> list[CaseSummary]:
        data = self.client.rpc("proofshield_list_unassigned_cases").execute().data
        if not isinstance(data, list):
            raise CaseStoreError(
                "Supabase unassigned-cases RPC returned an unexpected response"
            )
        return [CaseSummary.model_validate(row) for row in data]

    def claim_case(self, dispute_id: str, owner_id: str) -> bool:
        result = _rpc_status(
            self.client,
            "proofshield_claim_case",
            {
                "p_dispute_id": dispute_id,
                "p_owner_id": owner_id,
            },
        )
        if result == "CLAIMED":
            return True
        if result == "EXISTS":
            return False
        if result == "CASE_NOT_FOUND":
            raise CaseNotFoundError(f"case {dispute_id} was not found")
        if result == "ALREADY_CLAIMED":
            raise CaseConflictError(
                f"case {dispute_id} was claimed by another operator"
            )
        if result == "OWNER_NOT_AUTHORIZED":
            raise CaseConflictError("the operator is no longer active")
        raise CaseStoreError(f"unexpected claim-case status: {result}")

    def require_case_owner(self, dispute_id: str, owner_id: str) -> None:
        rows = (
            self.client.table("proofshield_cases")
            .select("dispute_id")
            .eq("dispute_id", dispute_id)
            .eq("owner_id", owner_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
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
        result = _rpc_status(
            self.client,
            "proofshield_register_evidence_file",
            {
                "p_dispute_id": dispute_id,
                "p_file_id": file_id,
                "p_original_name": original_name,
                "p_content_type": content_type,
                "p_size_bytes": size_bytes,
                "p_sha256": sha256,
                "p_storage_key": storage_key,
            },
        )
        if result == "CASE_NOT_FOUND":
            raise CaseNotFoundError(f"case {dispute_id} was not found")
        if result != "CREATED":
            raise EvidenceConflictError(f"evidence file {file_id} could not be registered")
        return self.get_evidence_file(dispute_id, file_id)

    def get_evidence_file(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileMetadata:
        return self.get_evidence_file_record(dispute_id, file_id).metadata

    def get_evidence_file_record(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileRecord:
        rows = (
            self.client.table("proofshield_evidence_files")
            .select(
                "file_id,dispute_id,original_name,content_type,size_bytes,sha256,"
                "storage_key,created_at"
            )
            .eq("file_id", file_id)
            .eq("dispute_id", dispute_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise CaseNotFoundError(
                f"evidence file {file_id} was not found for case {dispute_id}"
            )
        row = rows[0]
        return EvidenceFileRecord(
            metadata=EvidenceFileMetadata.model_validate(row),
            storage_key=row["storage_key"],
        )

    def list_evidence_files(self, dispute_id: str) -> list[EvidenceFileMetadata]:
        self._require_case(dispute_id)
        rows = (
            self.client.table("proofshield_evidence_files")
            .select(
                "file_id,dispute_id,original_name,content_type,size_bytes,sha256,created_at"
            )
            .eq("dispute_id", dispute_id)
            .order("created_at")
            .order("file_id")
            .execute()
            .data
        )
        return [EvidenceFileMetadata.model_validate(row) for row in rows]

    def add_evidence(self, dispute_id: str, document: EvidenceDocument) -> bool:
        result = _rpc_status(
            self.client,
            "proofshield_add_evidence",
            {
                "p_dispute_id": dispute_id,
                "p_evidence_id": document.evidence_id,
                "p_document_json": document.model_dump(mode="json"),
                "p_document_sha256": model_sha256(document),
                "p_evidence_type": str(document.evidence_type),
                "p_source_verified": document.source_verified,
            },
        )
        if result == "ADDED":
            return True
        if result == "EXISTS":
            return False
        if result == "CASE_NOT_FOUND":
            raise CaseNotFoundError(f"case {dispute_id} was not found")
        if result == "CONFLICT":
            raise EvidenceConflictError(
                f"evidence ID {document.evidence_id} is already attached elsewhere"
            )
        raise CaseStoreError(f"unexpected add-evidence status: {result}")

    def record_assessment(self, assessment: Assessment) -> None:
        result = _rpc_status(
            self.client,
            "proofshield_record_assessment",
            {
                "p_dispute_id": assessment.dispute_id,
                "p_decision": str(assessment.decision),
                "p_evidence_score": assessment.evidence_score,
            },
        )
        if result == "CASE_NOT_FOUND":
            raise CaseNotFoundError(f"case {assessment.dispute_id} was not found")
        if result != "RECORDED":
            raise CaseStoreError(f"unexpected assessment-record status: {result}")

    def save_draft(self, draft: ResponseDraft) -> bool:
        result = _rpc_status(
            self.client,
            "proofshield_save_response_draft",
            {
                "p_draft_id": draft.draft_id,
                "p_dispute_id": draft.dispute_id,
                "p_decision": str(draft.decision),
                "p_status": str(draft.status),
                "p_generator": draft.generator,
                "p_input_sha256": draft.input_sha256,
                "p_content_sha256": draft.content_sha256,
                "p_draft_json": draft.model_dump(mode="json"),
                "p_created_at": draft.created_at.isoformat(),
            },
        )
        if result == "CREATED":
            return True
        if result == "EXISTS":
            return False
        if result == "CASE_NOT_FOUND":
            raise CaseNotFoundError(f"case {draft.dispute_id} was not found")
        if result == "CONFLICT":
            raise DraftConflictError(
                f"draft {draft.draft_id} already exists with different content"
            )
        if result == "REJECTED":
            raise DraftConflictError("only pending SAFE_TO_DRAFT responses can be stored")
        raise CaseStoreError(f"unexpected save-draft status: {result}")

    def get_draft(self, dispute_id: str, draft_id: str) -> ResponseDraft:
        rows = (
            self.client.table("proofshield_response_drafts")
            .select("draft_json")
            .eq("draft_id", draft_id)
            .eq("dispute_id", dispute_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise DraftNotFoundError(
                f"draft {draft_id} was not found for case {dispute_id}"
            )
        return ResponseDraft.model_validate(rows[0]["draft_json"])

    def list_drafts(self, dispute_id: str) -> list[ResponseDraft]:
        self._require_case(dispute_id)
        rows = (
            self.client.table("proofshield_response_drafts")
            .select("draft_json")
            .eq("dispute_id", dispute_id)
            .order("created_at", desc=True)
            .order("draft_id")
            .execute()
            .data
        )
        return [ResponseDraft.model_validate(row["draft_json"]) for row in rows]

    def save_review(self, review: DraftReview) -> bool:
        result = _rpc_status(
            self.client,
            "proofshield_review_response_draft",
            {
                "p_draft_id": review.draft_id,
                "p_review_id": review.review_id,
                "p_decision": str(review.decision),
                "p_reviewer_label": review.reviewer_label,
                "p_reviewer_user_id": review.reviewer_user_id,
                "p_note": review.note,
                "p_request_sha256": review.request_sha256,
                "p_review_json": review.model_dump(mode="json"),
                "p_created_at": review.created_at.isoformat(),
            },
        )
        if result == "CREATED":
            return True
        if result == "EXISTS":
            return False
        if result == "DRAFT_NOT_FOUND":
            raise DraftNotFoundError(
                f"draft {review.draft_id} was not found for case {review.dispute_id}"
            )
        if result == "CONFLICT":
            raise ReviewConflictError(
                f"draft {review.draft_id} already has a different final review"
            )
        if result == "REJECTED":
            raise ReviewConflictError("the review request failed validation")
        raise CaseStoreError(f"unexpected save-review status: {result}")

    def get_review(self, dispute_id: str, draft_id: str) -> DraftReview:
        self.get_draft(dispute_id, draft_id)
        rows = (
            self.client.table("proofshield_draft_reviews")
            .select("review_json")
            .eq("draft_id", draft_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise ReviewNotFoundError(f"draft {draft_id} has not been reviewed")
        review = DraftReview.model_validate(rows[0]["review_json"])
        if review.dispute_id != dispute_id:
            raise ReviewNotFoundError(f"draft {draft_id} has not been reviewed")
        return review

    def get_history(self, dispute_id: str) -> list[CaseHistoryEntry]:
        self._require_case(dispute_id)
        rows = (
            self.client.table("proofshield_case_history")
            .select("sequence,dispute_id,action,reference_id,recorded_at,detail")
            .eq("dispute_id", dispute_id)
            .order("sequence")
            .execute()
            .data
        )
        return [CaseHistoryEntry.model_validate(row) for row in rows]

    def _require_case(self, dispute_id: str) -> None:
        rows = (
            self.client.table("proofshield_cases")
            .select("dispute_id")
            .eq("dispute_id", dispute_id)
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            raise CaseNotFoundError(f"case {dispute_id} was not found")
