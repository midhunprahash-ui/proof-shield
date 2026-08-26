from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.domain import EvidenceDocument, EvidenceType
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from proofshield.synthetic import make_case
from tests.auth_helpers import AUTH_HEADERS, TEST_AUTHENTICATOR, TEST_OPERATOR


def _client_with_conflict() -> tuple[TestClient, dict]:
    repository = InMemoryCaseRepository()
    case = make_case(41, "valid_delivery")
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    case.evidence.append(
        EvidenceDocument(
            evidence_id="invoice_wrong_order",
            evidence_type=EvidenceType.INVOICE,
            source_verified=True,
            order_id="order_from_another_purchase",
            payment_id=case.payment_id,
            amount=case.disputed_amount,
        )
    )
    repository.save_case(
        case,
        source="test",
        owner_id=str(TEST_OPERATOR.user_id),
    )
    for document in case.evidence:
        repository.add_evidence(case.dispute_id, document)
    client = TestClient(
        create_app(
            webhook_secret="local-secret",
            case_repository=repository,
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
            operator_authenticator=TEST_AUTHENTICATOR,
        ),
        headers=AUTH_HEADERS,
    )
    return client, case.model_dump(mode="json")


def test_operator_resolves_bad_evidence_without_deleting_original() -> None:
    client, case = _client_with_conflict()
    dispute_id = case["dispute_id"]
    request = {
        "evidence_id": "invoice_wrong_order",
        "action": "EXCLUDED_INCORRECT",
        "reason": "Operator verified this invoice belongs to a different order.",
    }

    before = client.get(f"/v1/cases/{dispute_id}/consistency")
    created = client.post(f"/v1/cases/{dispute_id}/resolutions", json=request)
    retry = client.post(f"/v1/cases/{dispute_id}/resolutions", json=request)
    resolutions = client.get(f"/v1/cases/{dispute_id}/resolutions")
    stored_case = client.get(f"/v1/cases/{dispute_id}")
    after = client.get(f"/v1/cases/{dispute_id}/consistency")
    assessment = client.post(f"/v1/cases/{dispute_id}/assessment")
    history = client.get(f"/v1/cases/{dispute_id}/history")

    assert before.json()["status"] == "CONFLICTS_FOUND"
    assert created.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == created.json()
    assert resolutions.json() == [created.json()]
    assert len(stored_case.json()["evidence"]) == len(case["evidence"])
    assert "invoice_wrong_order" in {
        item["evidence_id"] for item in stored_case.json()["evidence"]
    }
    assert after.json()["status"] == "CONSISTENT"
    assert after.json()["excluded_evidence_ids"] == ["invoice_wrong_order"]
    assert assessment.json()["decision"] == "SAFE_TO_DRAFT"
    assert [item["action"] for item in history.json()].count("EVIDENCE_RESOLVED") == 1


def test_resolution_rejects_invalid_replacement_and_requires_auth() -> None:
    client, case = _client_with_conflict()
    url = f"/v1/cases/{case['dispute_id']}/resolutions"
    request = {
        "evidence_id": "invoice_wrong_order",
        "action": "SUPERSEDED",
        "replacement_evidence_id": "delivery_0041",
        "reason": "Operator selected a replacement after checking both source files.",
    }

    wrong_type = client.post(url, json=request)
    unauthenticated = TestClient(client.app).get(url)

    assert wrong_type.status_code == 409
    assert "same evidence type" in wrong_type.json()["detail"]
    assert unauthenticated.status_code == 401
