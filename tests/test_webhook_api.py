import json
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.audit import AuditStatus
from proofshield.domain import Decision
from proofshield.webhook_security import calculate_webhook_signature

SECRET = "local-test-secret"


def make_payload(
    *,
    event: str = "payment.dispute.created",
    order_id: str | None = "order_demo_1",
) -> dict:
    now = datetime.now(UTC)
    return {
        "entity": "event",
        "account_id": "acc_demo",
        "event": event,
        "contains": ["payment", "dispute"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_demo_1",
                    "entity": "payment",
                    "amount": 250000,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": order_id,
                    "captured": True,
                }
            },
            "dispute": {
                "entity": {
                    "id": "disp_demo_1",
                    "entity": "dispute",
                    "payment_id": "pay_demo_1",
                    "amount": 250000,
                    "currency": "INR",
                    "reason_code": "goods_or_services_not_received_or_partially_received",
                    "respond_by": int((now + timedelta(days=5)).timestamp()),
                    "status": "open",
                    "phase": "chargeback",
                    "created_at": int(now.timestamp()),
                }
            },
        },
        "created_at": int(now.timestamp()),
    }


def encode_and_sign(payload: dict) -> tuple[bytes, dict[str, str]]:
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    return raw_body, {
        "content-type": "application/json",
        "x-razorpay-event-id": "event_demo_1",
        "x-razorpay-signature": calculate_webhook_signature(raw_body, SECRET),
    }


def make_client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            webhook_secret=SECRET,
            ledger_path=tmp_path / "webhook_audit.jsonl",
            database_path=tmp_path / "proofshield.sqlite3",
            evidence_storage_path=tmp_path / "evidence",
        )
    )


def test_verified_dispute_event_is_assessed_and_audited(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload())

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 202
    assert response.json() == {
        "event_id": "event_demo_1",
        "status": "PROCESSED",
        "dispute_id": "disp_demo_1",
        "decision": Decision.INSUFFICIENT_EVIDENCE,
        "detail": (
            "Webhook was verified and assessed. Evidence enrichment is still required "
            "before a response can be drafted."
        ),
    }
    entries = client.app.state.webhook_ledger.entries()
    assert [entry.status for entry in entries] == [
        AuditStatus.RECEIVED,
        AuditStatus.PROCESSED,
    ]
    stored_case = client.get("/v1/cases/disp_demo_1")
    assert stored_case.status_code == 200
    assert stored_case.json()["evidence"] == []


def test_duplicate_event_is_acknowledged_without_reprocessing(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload())

    first = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)
    duplicate = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "DUPLICATE"
    statuses = [entry.status for entry in client.app.state.webhook_ledger.entries()]
    assert statuses.count(AuditStatus.PROCESSED) == 1
    assert statuses[-1] == AuditStatus.DUPLICATE


def test_forged_signature_is_rejected_without_poisoning_idempotency(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload())
    headers["x-razorpay-signature"] = "0" * 64

    forged = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert forged.status_code == 401
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.REJECTED

    headers["x-razorpay-signature"] = calculate_webhook_signature(raw_body, SECRET)
    valid = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)
    assert valid.status_code == 202
    assert valid.json()["status"] == "PROCESSED"


def test_same_event_id_with_a_different_signed_body_is_rejected(tmp_path) -> None:
    client = make_client(tmp_path)
    first_body, first_headers = encode_and_sign(make_payload())
    client.post("/v1/webhooks/razorpay", content=first_body, headers=first_headers)

    changed_payload = make_payload()
    changed_payload["payload"]["dispute"]["entity"]["amount"] = 300000
    changed_body, changed_headers = encode_and_sign(changed_payload)
    conflict = client.post(
        "/v1/webhooks/razorpay", content=changed_body, headers=changed_headers
    )

    assert conflict.status_code == 409


def test_verified_non_created_event_is_ignored(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload(event="payment.dispute.won"))

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 202
    assert response.json()["status"] == "IGNORED"
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.IGNORED


def test_missing_order_id_is_accepted_for_later_enrichment(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload(order_id=None))

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 202
    assert response.json()["status"] == "NEEDS_ENRICHMENT"
    assert client.app.state.webhook_ledger.entries()[-1].status == (
        AuditStatus.NEEDS_ENRICHMENT
    )


def test_signed_malformed_contract_can_retry_after_correction(tmp_path) -> None:
    client = make_client(tmp_path)
    payload = make_payload()
    del payload["payload"]["dispute"]["entity"]["payment_id"]
    raw_body, headers = encode_and_sign(payload)

    invalid = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert invalid.status_code == 422
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.FAILED


def test_signed_invalid_json_is_rejected_and_audited(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body = b'{"event":'
    headers = {
        "content-type": "application/json",
        "x-razorpay-event-id": "event_invalid_json",
        "x-razorpay-signature": calculate_webhook_signature(raw_body, SECRET),
    }

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 422
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.REJECTED


def test_signed_json_without_event_type_is_rejected(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body = b'{"entity":"event"}'
    headers = {
        "content-type": "application/json",
        "x-razorpay-event-id": "event_missing_type",
        "x-razorpay-signature": calculate_webhook_signature(raw_body, SECRET),
    }

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 422
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.REJECTED


def test_signed_request_without_event_id_is_rejected_and_audited(tmp_path) -> None:
    client = make_client(tmp_path)
    raw_body, headers = encode_and_sign(make_payload())
    del headers["x-razorpay-event-id"]

    response = client.post("/v1/webhooks/razorpay", content=raw_body, headers=headers)

    assert response.status_code == 400
    assert client.app.state.webhook_ledger.entries()[-1].status == AuditStatus.REJECTED


def test_unconfigured_webhook_secret_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RAZORPAY_WEBHOOK_SECRET", raising=False)
    client = TestClient(
        create_app(
            webhook_secret=None,
            ledger_path=tmp_path / "audit.jsonl",
            database_path=tmp_path / "proofshield.sqlite3",
            evidence_storage_path=tmp_path / "evidence",
        )
    )
    raw_body = b"{}"

    response = client.post("/v1/webhooks/razorpay", content=raw_body)

    assert response.status_code == 503
