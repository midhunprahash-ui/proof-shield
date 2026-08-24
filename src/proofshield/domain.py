"""Typed contracts shared by the API, verifier, and evaluation tools."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class Decision(StrEnum):
    SAFE_TO_DRAFT = "SAFE_TO_DRAFT"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class DisputeReason(StrEnum):
    PRODUCT_NOT_RECEIVED = "PRODUCT_NOT_RECEIVED"
    OTHER = "OTHER"


class EvidenceType(StrEnum):
    INVOICE = "INVOICE"
    DELIVERY_PROOF = "DELIVERY_PROOF"
    CUSTOMER_COMMUNICATION = "CUSTOMER_COMMUNICATION"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class PaymentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    captured: bool

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class EvidenceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    evidence_type: EvidenceType
    source_file_id: str | None = Field(default=None, max_length=200)
    source_name: str | None = Field(default=None, max_length=255)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reviewed_by_human: bool = False
    source_verified: bool = False
    order_id: str | None = None
    payment_id: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    issued_at: AwareDatetime | None = None
    delivery_status: str | None = None
    customer_acknowledged_delivery: bool | None = None
    text: str | None = None


class DisputeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispute_id: str = Field(min_length=1)
    reason: DisputeReason
    payment_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    disputed_amount: Decimal = Field(gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    created_at: AwareDatetime
    respond_by: AwareDatetime
    payment: PaymentRecord
    evidence: list[EvidenceDocument] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class VerificationCheck(BaseModel):
    code: str
    outcome: CheckOutcome
    message: str


class Assessment(BaseModel):
    dispute_id: str
    decision: Decision
    evidence_score: float = Field(ge=0, le=1)
    summary: str
    checks: list[VerificationCheck]
    evaluated_at: AwareDatetime
    human_approval_required: bool = True


class LabelledSyntheticCase(BaseModel):
    """Development fixture with an expected result from a documented scenario."""

    scenario: str
    expected_decision: Decision
    case: DisputeCase
