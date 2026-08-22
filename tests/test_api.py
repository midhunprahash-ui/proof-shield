from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.domain import Decision
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from proofshield.synthetic import make_case

client = TestClient(
    create_app(
        case_repository=InMemoryCaseRepository(),
        evidence_file_store=InMemoryEvidenceFileStore(),
        webhook_ledger=InMemoryEventLedger(),
    )
)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "persistence": "supabase",
    }


def test_readiness_checks_persistence() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "persistence": "supabase"}


def test_missing_supabase_configuration_fails_closed(monkeypatch) -> None:
    for name in {
        "SUPABASE_PROJECT_REF",
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_EVIDENCE_BUCKET",
    }:
        monkeypatch.delenv(name, raising=False)
    unconfigured = TestClient(create_app())

    health = unconfigured.get("/health")
    cases = unconfigured.get("/v1/cases")

    assert health.status_code == 503
    assert health.json()["status"] == "configuration_required"
    assert cases.status_code == 503
    assert cases.json()["detail"] == "Supabase persistence is not configured."


def test_create_assessment() -> None:
    case = make_case(5, "valid_delivery")
    case.respond_by = datetime.now(UTC) + timedelta(days=5)

    response = client.post("/v1/assessments", json=case.model_dump(mode="json"))

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == Decision.SAFE_TO_DRAFT
    assert body["human_approval_required"] is True


def test_rejects_unknown_fields() -> None:
    case = make_case(6, "valid_delivery").model_dump(mode="json")
    case["unknown_field"] = "must not be silently accepted"

    response = client.post("/v1/assessments", json=case)

    assert response.status_code == 422


def test_rejects_datetime_without_timezone() -> None:
    case = make_case(7, "valid_delivery").model_dump(mode="json")
    case["respond_by"] = "2030-08-27T10:00:00"

    response = client.post("/v1/assessments", json=case)

    assert response.status_code == 422
