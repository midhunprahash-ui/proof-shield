from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from proofshield.synthetic import make_case
from tests.auth_helpers import AUTH_HEADERS, TEST_AUTHENTICATOR


def make_client() -> TestClient:
    return TestClient(
        create_app(
            webhook_secret="local-secret",
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
            operator_authenticator=TEST_AUTHENTICATOR,
        ),
        headers=AUTH_HEADERS,
    )


def create_case(client: TestClient, index: int) -> dict:
    case = make_case(index, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    response = client.post("/v1/cases", json=case.model_dump(mode="json"))
    assert response.status_code == 201
    return response.json()


def add_complete_file_backed_evidence(client: TestClient, case: dict) -> None:
    invoice_file = client.post(
        f"/v1/cases/{case['dispute_id']}/files",
        files={"file": ("invoice.pdf", b"%PDF-1.4 synthetic", "application/pdf")},
    ).json()
    delivery_file = client.post(
        f"/v1/cases/{case['dispute_id']}/files",
        files={"file": ("delivery.json", b'{"status":"delivered"}', "application/json")},
    ).json()
    invoice = client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json={
            "evidence_id": f"invoice_{case['dispute_id']}",
            "evidence_type": "INVOICE",
            "source_file_id": invoice_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case["order_id"],
            "payment_id": case["payment_id"],
            "amount": case["disputed_amount"],
        },
    )
    delivery = client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json={
            "evidence_id": f"delivery_{case['dispute_id']}",
            "evidence_type": "DELIVERY_PROOF",
            "source_file_id": delivery_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case["order_id"],
            "payment_id": case["payment_id"],
            "delivery_status": "delivered",
        },
    )
    assert invoice.status_code == delivery.status_code == 201


def test_complete_case_creates_idempotent_cited_draft() -> None:
    client = make_client()
    case = create_case(client, 101)
    add_complete_file_backed_evidence(client, case)

    first = client.post(f"/v1/cases/{case['dispute_id']}/drafts")
    duplicate = client.post(f"/v1/cases/{case['dispute_id']}/drafts")

    assert first.status_code == 201
    assert duplicate.status_code == 200
    assert duplicate.json()["draft_id"] == first.json()["draft_id"]
    assert first.json()["status"] == "PENDING_HUMAN_APPROVAL"
    assert first.json()["human_approval_required"] is True
    assert len(first.json()["citations"]) == 2
    assert len(client.get(f"/v1/cases/{case['dispute_id']}/drafts").json()) == 1
    history = client.get(f"/v1/cases/{case['dispute_id']}/history").json()
    assert [entry["action"] for entry in history].count("DRAFT_CREATED") == 1


def test_incomplete_case_refuses_to_draft() -> None:
    client = make_client()
    case = create_case(client, 102)

    response = client.post(f"/v1/cases/{case['dispute_id']}/drafts")

    assert response.status_code == 409
    assert "only SAFE_TO_DRAFT" in response.json()["detail"]


def test_unknown_draft_returns_not_found() -> None:
    client = make_client()
    case = create_case(client, 103)

    response = client.get(f"/v1/cases/{case['dispute_id']}/drafts/missing")

    assert response.status_code == 404
