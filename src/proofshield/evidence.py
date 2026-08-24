"""Human-reviewed evidence submission contracts."""

from __future__ import annotations

from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from proofshield.domain import EvidenceDocument, EvidenceType


class EvidenceSubmission(BaseModel):
    """Structured facts manually entered or confirmed from one evidence source."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=200)
    evidence_type: EvidenceType
    source_file_id: str | None = Field(default=None, min_length=1, max_length=200)
    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    human_confirmed_source: bool = False
    order_id: str | None = Field(default=None, max_length=200)
    payment_id: str | None = Field(default=None, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0)
    issued_at: AwareDatetime | None = None
    delivery_status: str | None = Field(default=None, max_length=100)
    customer_acknowledged_delivery: bool | None = None
    text: str | None = Field(default=None, max_length=10_000)

    @model_validator(mode="after")
    def require_file_or_manual_source(self) -> EvidenceSubmission:
        if self.source_file_id is None and self.source_name is None:
            raise ValueError("source_file_id or source_name is required")
        return self

    def to_document(
        self,
        *,
        resolved_source_name: str | None = None,
        resolved_source_sha256: str | None = None,
    ) -> EvidenceDocument:
        return EvidenceDocument(
            evidence_id=self.evidence_id,
            evidence_type=self.evidence_type,
            source_file_id=self.source_file_id,
            source_name=resolved_source_name or self.source_name,
            source_sha256=resolved_source_sha256,
            reviewed_by_human=True,
            source_verified=self.human_confirmed_source,
            order_id=self.order_id,
            payment_id=self.payment_id,
            amount=self.amount,
            issued_at=self.issued_at,
            delivery_status=self.delivery_status,
            customer_acknowledged_delivery=self.customer_acknowledged_delivery,
            text=self.text,
        )
