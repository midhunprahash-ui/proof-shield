"""Append-only operator resolutions for incorrect or superseded evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from proofshield.domain import DisputeCase, EvidenceDocument


class EvidenceResolutionAction(StrEnum):
    EXCLUDED_INCORRECT = "EXCLUDED_INCORRECT"
    SUPERSEDED = "SUPERSEDED"


class EvidenceResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=200)
    action: EvidenceResolutionAction
    replacement_evidence_id: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str = Field(min_length=10, max_length=2_000)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_replacement(self) -> EvidenceResolutionRequest:
        if self.action == EvidenceResolutionAction.EXCLUDED_INCORRECT:
            if self.replacement_evidence_id is not None:
                raise ValueError("excluded evidence cannot name a replacement")
        elif self.replacement_evidence_id is None:
            raise ValueError("superseded evidence requires a replacement")
        if self.replacement_evidence_id == self.evidence_id:
            raise ValueError("evidence cannot replace itself")
        return self


class EvidenceResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_id: str = Field(min_length=1, max_length=200)
    dispute_id: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1, max_length=200)
    action: EvidenceResolutionAction
    replacement_evidence_id: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str = Field(min_length=10, max_length=2_000)
    resolved_by: UUID
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime


class EvidenceResolutionError(RuntimeError):
    pass


def create_evidence_resolution(
    case: DisputeCase,
    existing: list[EvidenceResolution],
    request: EvidenceResolutionRequest,
    *,
    resolved_by: UUID,
    created_at: datetime | None = None,
) -> EvidenceResolution:
    by_id = {document.evidence_id: document for document in case.evidence}
    target = by_id.get(request.evidence_id)
    if target is None:
        raise EvidenceResolutionError(
            f"evidence {request.evidence_id} was not found for this case"
        )

    existing_for_target = next(
        (
            resolution
            for resolution in existing
            if resolution.evidence_id == target.evidence_id
        ),
        None,
    )
    if existing_for_target is not None:
        if (
            existing_for_target.action == request.action
            and existing_for_target.replacement_evidence_id
            == request.replacement_evidence_id
            and existing_for_target.reason == request.reason
            and existing_for_target.resolved_by == resolved_by
        ):
            return existing_for_target.model_copy(deep=True)
        raise EvidenceResolutionError("this evidence already has an immutable resolution")

    resolved_ids = {resolution.evidence_id for resolution in existing}
    replacement_ids = {
        resolution.replacement_evidence_id
        for resolution in existing
        if resolution.replacement_evidence_id is not None
    }
    if target.evidence_id in replacement_ids:
        raise EvidenceResolutionError(
            "evidence already used as a replacement cannot be resolved"
        )

    replacement: EvidenceDocument | None = None
    if request.replacement_evidence_id is not None:
        replacement = by_id.get(request.replacement_evidence_id)
        if replacement is None:
            raise EvidenceResolutionError(
                f"replacement evidence {request.replacement_evidence_id} was not found"
            )
        if replacement.evidence_id in resolved_ids:
            raise EvidenceResolutionError("replacement evidence is already resolved")
        if replacement.evidence_type != target.evidence_type:
            raise EvidenceResolutionError(
                "replacement evidence must have the same evidence type"
            )

    payload = {
        "dispute_id": case.dispute_id,
        "evidence_id": request.evidence_id,
        "action": request.action,
        "replacement_evidence_id": request.replacement_evidence_id,
        "reason": request.reason,
        "resolved_by": str(resolved_by),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    request_sha256 = hashlib.sha256(encoded).hexdigest()
    resolved_at = created_at or datetime.now(UTC)
    if resolved_at.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    return EvidenceResolution(
        resolution_id=f"resolution_{request_sha256[:32]}",
        dispute_id=case.dispute_id,
        evidence_id=request.evidence_id,
        action=request.action,
        replacement_evidence_id=request.replacement_evidence_id,
        reason=request.reason,
        resolved_by=resolved_by,
        request_sha256=request_sha256,
        created_at=resolved_at,
    )
