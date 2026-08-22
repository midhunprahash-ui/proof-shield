"""Convert a Razorpay dispute event into ProofShield's internal case contract."""

from __future__ import annotations

from datetime import UTC, datetime

from proofshield.domain import DisputeCase, DisputeReason, PaymentRecord
from proofshield.webhook_models import RazorpayDisputeWebhook

PRODUCT_NOT_RECEIVED_REASON_CODES = {
    "goods_or_services_not_received_or_partially_received",
    "goods_not_received",
    "product_not_received",
}


class WebhookAdaptationError(ValueError):
    """Raised when a valid webhook lacks data required by our domain contract."""


def adapt_dispute_created_event(event: RazorpayDisputeWebhook) -> DisputeCase:
    if event.event != "payment.dispute.created":
        raise WebhookAdaptationError(f"unsupported event type: {event.event}")

    payment = event.payload.payment.entity
    dispute = event.payload.dispute.entity
    if not payment.order_id:
        raise WebhookAdaptationError("the payment does not contain an order_id")

    reason = (
        DisputeReason.PRODUCT_NOT_RECEIVED
        if dispute.reason_code.lower() in PRODUCT_NOT_RECEIVED_REASON_CODES
        else DisputeReason.OTHER
    )
    return DisputeCase(
        dispute_id=dispute.id,
        reason=reason,
        payment_id=dispute.payment_id,
        order_id=payment.order_id,
        disputed_amount=dispute.major_amount,
        currency=dispute.currency,
        created_at=datetime.fromtimestamp(dispute.created_at, tz=UTC),
        respond_by=datetime.fromtimestamp(dispute.respond_by, tz=UTC),
        payment=PaymentRecord(
            payment_id=payment.id,
            order_id=payment.order_id,
            amount=payment.major_amount,
            currency=payment.currency,
            captured=payment.captured or payment.status.lower() == "captured",
        ),
        evidence=[],
    )
