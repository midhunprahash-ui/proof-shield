from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import app
from proofshield.domain import Decision
from proofshield.synthetic import make_case

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


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
