from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.domain import Decision
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from proofshield.operator_auth import OperatorIdentity, PublicAuthConfig
from proofshield.synthetic import make_case
from tests.auth_helpers import (
    AUTH_HEADERS,
    TEST_ACCESS_TOKEN,
    TEST_AUTHENTICATOR,
    FakeOperatorAuthenticator,
)

client = TestClient(
    create_app(
        case_repository=InMemoryCaseRepository(),
        evidence_file_store=InMemoryEvidenceFileStore(),
        webhook_ledger=InMemoryEventLedger(),
        operator_authenticator=TEST_AUTHENTICATOR,
    ),
    headers=AUTH_HEADERS,
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
        "SUPABASE_PUBLISHABLE_KEY",
    }:
        monkeypatch.delenv(name, raising=False)
    unconfigured = TestClient(create_app())

    health = unconfigured.get("/health")
    cases = unconfigured.get("/v1/cases")

    assert health.status_code == 503
    assert health.json()["status"] == "configuration_required"
    assert cases.status_code == 503
    assert cases.json()["detail"] == (
        "Supabase operator authentication is not configured."
    )


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


def test_local_frontend_origin_is_allowed_without_credentials() -> None:
    response = client.options(
        "/v1/cases",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") is None
    assert "authorization" in response.headers[
        "access-control-allow-headers"
    ].lower()


def test_case_api_requires_a_verified_active_operator() -> None:
    missing = client.get("/v1/cases", headers={"Authorization": ""})
    forbidden = client.get(
        "/v1/cases",
        headers={"Authorization": "Bearer signed-in-but-not-operator"},
    )

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert forbidden.status_code == 403


def test_operator_cannot_read_another_operators_case() -> None:
    repository = InMemoryCaseRepository()
    file_store = InMemoryEvidenceFileStore()
    ledger = InMemoryEventLedger()
    first_client = TestClient(
        create_app(
            operator_authenticator=TEST_AUTHENTICATOR,
            case_repository=repository,
            evidence_file_store=file_store,
            webhook_ledger=ledger,
        ),
        headers=AUTH_HEADERS,
    )
    case = make_case(901, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    assert first_client.post("/v1/cases", json=case.model_dump(mode="json")).status_code == 201

    second_identity = OperatorIdentity(
        user_id="22222222-2222-4222-8222-222222222222",
        email="second@example.com",
        display_name="Second operator",
    )
    second_client = TestClient(
        create_app(
            operator_authenticator=FakeOperatorAuthenticator(second_identity),
            case_repository=repository,
            evidence_file_store=file_store,
            webhook_ledger=ledger,
        ),
        headers={"Authorization": f"Bearer {TEST_ACCESS_TOKEN}"},
    )

    assert second_client.get("/v1/cases").json() == []
    assert second_client.get(f"/v1/cases/{case.dispute_id}").status_code == 404


def test_operator_atomically_claims_an_unassigned_webhook_case() -> None:
    repository = InMemoryCaseRepository()
    case = make_case(902, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    assert repository.save_case(case, source="razorpay_webhook") is True
    configured = TestClient(
        create_app(
            operator_authenticator=TEST_AUTHENTICATOR,
            case_repository=repository,
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
        ),
        headers=AUTH_HEADERS,
    )

    assert configured.get("/v1/cases").json() == []
    unassigned = configured.get("/v1/cases/unassigned")
    claimed = configured.post(f"/v1/cases/{case.dispute_id}/claim")

    assert unassigned.status_code == 200
    assert [item["dispute_id"] for item in unassigned.json()] == [case.dispute_id]
    assert claimed.status_code == 200
    assert claimed.json()["dispute_id"] == case.dispute_id
    assert configured.get("/v1/cases/unassigned").json() == []
    assert [item["dispute_id"] for item in configured.get("/v1/cases").json()] == [
        case.dispute_id
    ]
    history = configured.get(f"/v1/cases/{case.dispute_id}/history").json()
    assert [item["action"] for item in history] == ["CASE_CREATED", "CASE_CLAIMED"]


def test_claim_race_does_not_reassign_case_between_operators() -> None:
    repository = InMemoryCaseRepository()
    case = make_case(903, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    repository.save_case(case, source="razorpay_webhook")
    shared = {
        "case_repository": repository,
        "evidence_file_store": InMemoryEvidenceFileStore(),
        "webhook_ledger": InMemoryEventLedger(),
    }
    first = TestClient(
        create_app(operator_authenticator=TEST_AUTHENTICATOR, **shared),
        headers=AUTH_HEADERS,
    )
    second_identity = OperatorIdentity(
        user_id="22222222-2222-4222-8222-222222222222",
        email="second@example.com",
        display_name="Second operator",
    )
    second = TestClient(
        create_app(
            operator_authenticator=FakeOperatorAuthenticator(second_identity),
            **shared,
        ),
        headers=AUTH_HEADERS,
    )

    assert first.post(f"/v1/cases/{case.dispute_id}/claim").status_code == 200
    raced = second.post(f"/v1/cases/{case.dispute_id}/claim")

    assert raced.status_code == 409
    assert second.get(f"/v1/cases/{case.dispute_id}").status_code == 404


def test_public_auth_config_contains_only_browser_safe_values() -> None:
    config = PublicAuthConfig(
        supabase_url="https://qoujhmqkjicvcwoiyqkp.supabase.co",
        supabase_publishable_key="sb_publishable_test_only",
    )
    configured = TestClient(
        create_app(
            operator_authenticator=TEST_AUTHENTICATOR,
            public_auth_config=config,
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
        )
    )

    response = configured.get("/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == config.model_dump(mode="json")
    assert "secret" not in response.text.casefold()
