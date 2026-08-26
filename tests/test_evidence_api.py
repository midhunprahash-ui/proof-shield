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
from tests.auth_helpers import AUTH_HEADERS, TEST_AUTHENTICATOR


def make_client(tmp_path) -> TestClient:
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


def create_case(client: TestClient, index: int = 1) -> dict:
    case = make_case(index, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    response = client.post("/v1/cases", json=case.model_dump(mode="json"))
    assert response.status_code == 201
    return response.json()


def invoice_payload(
    case: dict, *, confirmed: bool = True, source_file_id: str | None = None
) -> dict:
    payload = {
        "evidence_id": "invoice_manual_1",
        "evidence_type": "INVOICE",
        "human_confirmed_source": confirmed,
        "order_id": case["order_id"],
        "payment_id": case["payment_id"],
        "amount": case["disputed_amount"],
    }
    if source_file_id is None:
        payload["source_name"] = "synthetic-invoice.pdf"
    else:
        payload["source_file_id"] = source_file_id
    return payload


def delivery_payload(
    case: dict, *, confirmed: bool = True, source_file_id: str | None = None
) -> dict:
    payload = {
        "evidence_id": "delivery_manual_1",
        "evidence_type": "DELIVERY_PROOF",
        "human_confirmed_source": confirmed,
        "order_id": case["order_id"],
        "payment_id": case["payment_id"],
        "delivery_status": "delivered",
    }
    if source_file_id is None:
        payload["source_name"] = "synthetic-courier-record.json"
    else:
        payload["source_file_id"] = source_file_id
    return payload


def upload_file(
    client: TestClient,
    case: dict,
    *,
    name: str,
    content: bytes,
    content_type: str,
) -> dict:
    response = client.post(
        f"/v1/cases/{case['dispute_id']}/files",
        files={"file": (name, content, content_type)},
    )
    assert response.status_code == 201
    return response.json()


def test_complete_manual_evidence_changes_case_to_safe_to_draft(tmp_path) -> None:
    client = make_client(tmp_path)
    case = create_case(client)
    invoice_file = upload_file(
        client,
        case,
        name="invoice.pdf",
        content=b"%PDF-1.4 synthetic invoice bytes",
        content_type="application/pdf",
    )
    delivery_file = upload_file(
        client,
        case,
        name="delivery.json",
        content=b'{"status":"delivered"}',
        content_type="application/json",
    )

    invoice_response = client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=invoice_payload(case, source_file_id=invoice_file["file_id"]),
    )
    delivery_response = client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=delivery_payload(case, source_file_id=delivery_file["file_id"]),
    )
    assessment = client.post(f"/v1/cases/{case['dispute_id']}/assessment")

    assert invoice_response.status_code == 201
    assert delivery_response.status_code == 201
    assert assessment.status_code == 200
    assert assessment.json()["decision"] == Decision.SAFE_TO_DRAFT
    assert assessment.json()["human_approval_required"] is True

    stored = client.get(f"/v1/cases/{case['dispute_id']}").json()
    assert len(stored["evidence"]) == 2
    assert stored["evidence"][0]["source_sha256"] is not None
    files = client.get(f"/v1/cases/{case['dispute_id']}/files").json()
    assert {item["original_name"] for item in files} == {"invoice.pdf", "delivery.json"}
    summary = client.get("/v1/cases").json()[0]
    assert summary["evidence_count"] == 2
    history = client.get(f"/v1/cases/{case['dispute_id']}/history").json()
    assert [entry["action"] for entry in history] == [
        "CASE_CREATED",
        "FILE_UPLOADED",
        "FILE_UPLOADED",
        "EVIDENCE_ADDED",
        "EVIDENCE_ADDED",
        "ASSESSED",
    ]


def test_unconfirmed_evidence_requires_review(tmp_path) -> None:
    client = make_client(tmp_path)
    case = create_case(client, index=2)
    client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=invoice_payload(case),
    )
    delivery = delivery_payload(case, confirmed=False)
    delivery["evidence_id"] = "delivery_unconfirmed"
    client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=delivery,
    )

    assessment = client.post(f"/v1/cases/{case['dispute_id']}/assessment")

    assert assessment.json()["decision"] == Decision.NEEDS_REVIEW
    assert "DELIVERY_SOURCE_UNVERIFIED" in {
        check["code"] for check in assessment.json()["checks"]
    }


def test_mismatched_delivery_stays_linked_but_is_not_trusted(tmp_path) -> None:
    client = make_client(tmp_path)
    case = create_case(client, index=3)
    client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=invoice_payload(case),
    )
    delivery = delivery_payload(case)
    delivery["evidence_id"] = "delivery_wrong_order"
    delivery["order_id"] = "order_belongs_to_someone_else"
    client.post(
        f"/v1/cases/{case['dispute_id']}/evidence",
        json=delivery,
    )

    assessment = client.post(f"/v1/cases/{case['dispute_id']}/assessment")

    assert assessment.json()["decision"] == Decision.NEEDS_REVIEW
    assert "DELIVERY_FACT_MISMATCH" in {
        check["code"] for check in assessment.json()["checks"]
    }


def test_evidence_for_unknown_case_is_rejected(tmp_path) -> None:
    client = make_client(tmp_path)
    case = make_case(4, "valid_delivery").model_dump(mode="json")

    response = client.post(
        "/v1/cases/missing/evidence",
        json=invoice_payload(case),
    )

    assert response.status_code == 404


def test_case_creation_rejects_embedded_evidence(tmp_path) -> None:
    client = make_client(tmp_path)
    case = make_case(5, "valid_delivery")
    case.respond_by = datetime.now(UTC) + timedelta(days=5)

    response = client.post("/v1/cases", json=case.model_dump(mode="json"))

    assert response.status_code == 400


def test_file_from_one_case_cannot_be_used_by_another(tmp_path) -> None:
    client = make_client(tmp_path)
    first = create_case(client, index=6)
    second = create_case(client, index=7)
    uploaded = upload_file(
        client,
        first,
        name="invoice.pdf",
        content=b"%PDF-1.4 belongs to first case",
        content_type="application/pdf",
    )

    response = client.post(
        f"/v1/cases/{second['dispute_id']}/evidence",
        json=invoice_payload(second, source_file_id=uploaded["file_id"]),
    )

    assert response.status_code == 404


def test_unsupported_file_type_is_rejected(tmp_path) -> None:
    client = make_client(tmp_path)
    case = create_case(client, index=8)

    response = client.post(
        f"/v1/cases/{case['dispute_id']}/files",
        files={"file": ("script.exe", b"not allowed", "application/octet-stream")},
    )

    assert response.status_code == 415
