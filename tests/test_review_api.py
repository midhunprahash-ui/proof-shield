import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from proofshield.synthetic import make_case
from tests.auth_helpers import AUTH_HEADERS, TEST_AUTHENTICATOR, TEST_OPERATOR

OPERATOR_HEADERS = AUTH_HEADERS


def make_client() -> tuple[TestClient, InMemoryEvidenceFileStore]:
    file_store = InMemoryEvidenceFileStore()
    client = TestClient(
        create_app(
            webhook_secret="local-secret",
            operator_authenticator=TEST_AUTHENTICATOR,
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=file_store,
            webhook_ledger=InMemoryEventLedger(),
        ),
        headers=AUTH_HEADERS,
    )
    return client, file_store


def create_draft(client: TestClient, index: int) -> tuple[dict, dict]:
    case = make_case(index, "valid_delivery").model_copy(update={"evidence": []})
    case.respond_by = datetime.now(UTC) + timedelta(days=5)
    created = client.post("/v1/cases", json=case.model_dump(mode="json"))
    assert created.status_code == 201
    case_json = created.json()

    invoice_file = client.post(
        f"/v1/cases/{case.dispute_id}/files",
        files={"file": ("invoice.pdf", b"%PDF-1.4 approved invoice", "application/pdf")},
    ).json()
    delivery_file = client.post(
        f"/v1/cases/{case.dispute_id}/files",
        files={
            "file": (
                "delivery.json",
                b'{"status":"delivered"}',
                "application/json",
            )
        },
    ).json()
    for payload in (
        {
            "evidence_id": f"invoice_{case.dispute_id}",
            "evidence_type": "INVOICE",
            "source_file_id": invoice_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case.order_id,
            "payment_id": case.payment_id,
            "amount": str(case.disputed_amount),
        },
        {
            "evidence_id": f"delivery_{case.dispute_id}",
            "evidence_type": "DELIVERY_PROOF",
            "source_file_id": delivery_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case.order_id,
            "payment_id": case.payment_id,
            "delivery_status": "delivered",
        },
    ):
        response = client.post(
            f"/v1/cases/{case.dispute_id}/evidence",
            json=payload,
        )
        assert response.status_code == 201
    draft = client.post(f"/v1/cases/{case.dispute_id}/drafts")
    assert draft.status_code == 201
    return case_json, draft.json()


def review_url(case: dict, draft: dict) -> str:
    return f"/v1/cases/{case['dispute_id']}/drafts/{draft['draft_id']}/reviews"


def packet_url(case: dict, draft: dict) -> str:
    return f"/v1/cases/{case['dispute_id']}/drafts/{draft['draft_id']}/packet"


def test_operator_bearer_token_is_required_for_review_and_packet() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 201)

    review = client.post(
        review_url(case, draft),
        json={"decision": "APPROVED"},
        headers={"Authorization": ""},
    )
    packet = client.get(packet_url(case, draft), headers={"Authorization": ""})

    assert review.status_code == 401
    assert packet.status_code == 401


def test_case_endpoints_fail_closed_without_operator_authenticator() -> None:
    client = TestClient(
        create_app(
            webhook_secret="local-secret",
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
        ),
        headers=AUTH_HEADERS,
    )
    response = client.get("/v1/cases")

    assert response.status_code == 503
    assert "authentication is not configured" in response.json()["detail"]


def test_approved_review_is_idempotent_and_exports_verified_zip() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 202)
    payload = {
        "decision": "APPROVED",
        "note": "Invoice and delivery record checked.",
    }

    before_review = client.get(packet_url(case, draft), headers=OPERATOR_HEADERS)
    first = client.post(review_url(case, draft), json=payload, headers=OPERATOR_HEADERS)
    retry = client.post(review_url(case, draft), json=payload, headers=OPERATOR_HEADERS)
    stored_review = client.get(
        review_url(case, draft).removesuffix("s"),
        headers=OPERATOR_HEADERS,
    )
    packet = client.get(packet_url(case, draft), headers=OPERATOR_HEADERS)
    repeated_packet = client.get(packet_url(case, draft), headers=OPERATOR_HEADERS)

    assert before_review.status_code == 409
    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert first.json()["reviewer_user_id"] == str(TEST_OPERATOR.user_id)
    assert first.json()["reviewer_label"] == TEST_OPERATOR.display_name
    assert stored_review.json() == first.json()
    assert packet.status_code == 200
    assert packet.headers["content-type"] == "application/zip"
    assert packet.content == repeated_packet.content
    assert packet.headers["x-proofshield-packet-sha256"] == hashlib.sha256(
        packet.content
    ).hexdigest()

    with zipfile.ZipFile(io.BytesIO(packet.content)) as archive:
        names = set(archive.namelist())
        assert {
            "manifest.json",
            "case.json",
            "draft.json",
            "review.json",
            "response.txt",
            "evidence/E1_invoice.pdf",
            "evidence/E2_delivery.json",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["review_decision"] == "APPROVED"
        assert manifest["draft_content_sha256"] == draft["content_sha256"]
        assert packet.headers["x-proofshield-manifest-sha256"] == manifest[
            "manifest_sha256"
        ]
        for entry in manifest["evidence"]:
            assert hashlib.sha256(archive.read(entry["packet_path"])).hexdigest() == entry[
                "sha256"
            ]

    history = client.get(f"/v1/cases/{case['dispute_id']}/history").json()
    assert [entry["action"] for entry in history].count("DRAFT_APPROVED") == 1


def test_conflicting_second_review_is_rejected() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 203)
    approved = client.post(
        review_url(case, draft),
        json={"decision": "APPROVED"},
        headers=OPERATOR_HEADERS,
    )
    changed = client.post(
        review_url(case, draft),
        json={
            "decision": "REJECTED",
            "note": "Changed decision.",
        },
        headers=OPERATOR_HEADERS,
    )

    assert approved.status_code == 201
    assert changed.status_code == 409


def test_rejected_draft_cannot_export_packet() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 204)

    rejected = client.post(
        review_url(case, draft),
        json={
            "decision": "REJECTED",
            "note": "Delivery record needs manual correction.",
        },
        headers=OPERATOR_HEADERS,
    )
    packet = client.get(packet_url(case, draft), headers=OPERATOR_HEADERS)

    assert rejected.status_code == 201
    assert packet.status_code == 409
    assert "only an approved draft" in packet.json()["detail"]


def test_rejection_requires_a_reason() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 205)

    response = client.post(
        review_url(case, draft),
        json={"decision": "REJECTED"},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422


def test_reviewer_identity_cannot_be_supplied_by_the_caller() -> None:
    client, _files = make_client()
    case, draft = create_draft(client, 208)

    response = client.post(
        review_url(case, draft),
        json={"decision": "APPROVED", "reviewer_label": "forged-admin"},
        headers=OPERATOR_HEADERS,
    )

    assert response.status_code == 422


def test_packet_fails_closed_when_stored_bytes_are_changed() -> None:
    client, file_store = make_client()
    case, draft = create_draft(client, 206)
    client.post(
        review_url(case, draft),
        json={"decision": "APPROVED"},
        headers=OPERATOR_HEADERS,
    )
    first_key = next(iter(file_store.blobs))
    file_store.blobs[first_key] = b"tampered bytes"

    packet = client.get(packet_url(case, draft), headers=OPERATOR_HEADERS)

    assert packet.status_code == 409
    assert "failed its SHA-256 check" in packet.json()["detail"]
