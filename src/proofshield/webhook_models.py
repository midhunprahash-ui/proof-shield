"""Minimal, official-payload-compatible Razorpay webhook contracts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RazorpayPaymentEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    amount: int = Field(gt=0, description="Amount in currency subunits")
    currency: str = Field(min_length=3, max_length=3)
    status: str = Field(min_length=1)
    order_id: str | None = None
    captured: bool = False

    @property
    def major_amount(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)


class RazorpayDisputeEntity(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    payment_id: str = Field(min_length=1)
    amount: int = Field(gt=0, description="Amount in currency subunits")
    currency: str = Field(min_length=3, max_length=3)
    reason_code: str = Field(min_length=1)
    respond_by: int = Field(gt=0)
    status: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    created_at: int = Field(gt=0)

    @property
    def major_amount(self) -> Decimal:
        return Decimal(self.amount) / Decimal(100)


class PaymentEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity: RazorpayPaymentEntity


class DisputeEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity: RazorpayDisputeEntity


class RazorpayWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    payment: PaymentEnvelope
    dispute: DisputeEnvelope


class RazorpayDisputeWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity: Literal["event"]
    account_id: str = Field(min_length=1)
    event: str = Field(min_length=1)
    payload: RazorpayWebhookPayload
    created_at: int = Field(gt=0)
