from datetime import UTC, datetime
from decimal import Decimal

import pytest

from proofshield.domain import DisputeReason
from proofshield.webhook_adapter import WebhookAdaptationError, adapt_dispute_created_event
from proofshield.webhook_models import RazorpayDisputeWebhook


def make_payload(*, event: str = "payment.dispute.created", order_id: str | None = "order_1"):
    return {
        "entity": "event",
        "account_id": "acc_demo",
        "event": event,
        "contains": ["payment", "dispute"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_1",
                    "entity": "payment",
                    "amount": 125000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": order_id,
                    "captured": True,
                    "extra_official_field": "ignored at the adapter boundary",
                }
            },
            "dispute": {
                "entity": {
                    "id": "disp_1",
                    "entity": "dispute",
                    "payment_id": "pay_1",
                    "amount": 125000,
                    "currency": "INR",
                    "reason_code": "goods_or_services_not_received_or_partially_received",
                    "respond_by": 1914048000,
                    "status": "open",
                    "phase": "chargeback",
                    "created_at": 1913616000,
                }
            },
        },
        "created_at": 1913616000,
    }


def test_adapter_converts_subunits_and_reason_without_inventing_evidence() -> None:
    event = RazorpayDisputeWebhook.model_validate(make_payload())

    case = adapt_dispute_created_event(event)

    assert case.reason == DisputeReason.PRODUCT_NOT_RECEIVED
    assert case.disputed_amount == Decimal("1250")
    assert case.payment.amount == Decimal("1250")
    assert case.created_at == datetime.fromtimestamp(1913616000, tz=UTC)
    assert case.evidence == []


def test_adapter_requires_an_order_id() -> None:
    event = RazorpayDisputeWebhook.model_validate(make_payload(order_id=None))

    with pytest.raises(WebhookAdaptationError, match="order_id"):
        adapt_dispute_created_event(event)


def test_adapter_rejects_a_different_event_type() -> None:
    event = RazorpayDisputeWebhook.model_validate(make_payload(event="payment.dispute.won"))

    with pytest.raises(WebhookAdaptationError, match="unsupported event"):
        adapt_dispute_created_event(event)
