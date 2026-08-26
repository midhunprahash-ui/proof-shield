"""Immutable human review contracts for response drafts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DraftReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_rejection_reason(self) -> DraftReviewRequest:
        if self.decision == ReviewDecision.REJECTED and self.note is None:
            raise ValueError("a rejection note is required")
        return self


class DraftReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1, max_length=200)
    dispute_id: str = Field(min_length=1, max_length=200)
    draft_id: str = Field(min_length=1, max_length=200)
    decision: ReviewDecision
    reviewer_user_id: str | None = Field(default=None, max_length=200)
    reviewer_label: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2_000)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime

    @model_validator(mode="after")
    def require_rejection_reason(self) -> DraftReview:
        if self.decision == ReviewDecision.REJECTED and self.note is None:
            raise ValueError("a rejection note is required")
        return self


def create_draft_review(
    dispute_id: str,
    draft_id: str,
    request: DraftReviewRequest,
    *,
    reviewer_user_id: str,
    reviewer_label: str,
    created_at: datetime | None = None,
) -> DraftReview:
    request_payload = {
        "dispute_id": dispute_id,
        "draft_id": draft_id,
        "decision": request.decision,
        "reviewer_user_id": reviewer_user_id,
        "reviewer_label": reviewer_label,
        "note": request.note,
    }
    encoded = json.dumps(
        request_payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    request_sha256 = hashlib.sha256(encoded).hexdigest()
    reviewed_at = created_at or datetime.now(UTC)
    if reviewed_at.tzinfo is None:
        raise ValueError("created_at must include a timezone")
    return DraftReview(
        review_id=f"review_{request_sha256[:32]}",
        dispute_id=dispute_id,
        draft_id=draft_id,
        decision=request.decision,
        reviewer_user_id=reviewer_user_id,
        reviewer_label=reviewer_label,
        note=request.note,
        request_sha256=request_sha256,
        created_at=reviewed_at,
    )
