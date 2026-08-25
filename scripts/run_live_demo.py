"""Seed and verify one clearly labelled ProofShield live demonstration case."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.domain import DisputeCase, DisputeReason, PaymentRecord
from proofshield.supabase_runtime import SupabaseSettings

EXPECTED_PROJECT_REF = "qoujhmqkjicvcwoiyqkp"


class LiveDemoError(RuntimeError):
    """Raised when the guarded live demonstration workflow fails closed."""


def run_demo(
    client: TestClient,
    *,
    operator_secret: str,
    label: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the complete API flow and return a secret-free verification record."""

    if len(operator_secret) < 32:
        raise LiveDemoError("the operator secret must contain at least 32 characters")
    started_at = now or datetime.now(UTC)
    if started_at.tzinfo is None:
        raise LiveDemoError("the demo timestamp must include a timezone")
    normalized_label = _normalize_label(label)
    case = _demo_case(normalized_label, started_at)

    created = _expect(
        client.post("/v1/cases", json=case.model_dump(mode="json")),
        {201},
        "create demonstration case",
    ).json()
    case_path = f"/v1/cases/{case.dispute_id}"

    invoice_file = _expect(
        client.post(
            f"{case_path}/files",
            files={
                "file": (
                    "proofshield-demo-invoice.pdf",
                    b"%PDF-1.4\nProofShield synthetic demonstration invoice\n%%EOF",
                    "application/pdf",
                )
            },
        ),
        {201},
        "upload demonstration invoice",
    ).json()
    delivery_file = _expect(
        client.post(
            f"{case_path}/files",
            files={
                "file": (
                    "proofshield-demo-delivery.json",
                    json.dumps(
                        {
                            "synthetic_demo": True,
                            "status": "delivered",
                            "order_id": case.order_id,
                        },
                        sort_keys=True,
                    ).encode(),
                    "application/json",
                )
            },
        ),
        {201},
        "upload demonstration delivery record",
    ).json()

    evidence_payloads = (
        {
            "evidence_id": f"invoice_{normalized_label}",
            "evidence_type": "INVOICE",
            "source_file_id": invoice_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case.order_id,
            "payment_id": case.payment_id,
            "amount": str(case.disputed_amount),
        },
        {
            "evidence_id": f"delivery_{normalized_label}",
            "evidence_type": "DELIVERY_PROOF",
            "source_file_id": delivery_file["file_id"],
            "human_confirmed_source": True,
            "order_id": case.order_id,
            "payment_id": case.payment_id,
            "delivery_status": "delivered",
        },
    )
    for evidence in evidence_payloads:
        _expect(
            client.post(f"{case_path}/evidence", json=evidence),
            {201},
            f"add {evidence['evidence_type'].lower()} evidence",
        )

    assessment = _expect(
        client.post(f"{case_path}/assessment"),
        {200},
        "assess demonstration case",
    ).json()
    if assessment["decision"] != "SAFE_TO_DRAFT":
        raise LiveDemoError(
            f"expected SAFE_TO_DRAFT, received {assessment['decision']}"
        )

    draft = _expect(
        client.post(f"{case_path}/drafts"),
        {201},
        "create evidence-grounded draft",
    ).json()
    review_path = f"{case_path}/drafts/{draft['draft_id']}/reviews"
    packet_path = f"{case_path}/drafts/{draft['draft_id']}/packet"
    operator_headers = {"X-ProofShield-Operator-Secret": operator_secret}

    _expect(
        client.post(
            review_path,
            json={"decision": "APPROVED", "reviewer_label": "milestone-9-demo"},
        ),
        {401},
        "prove anonymous review is blocked",
    )
    _expect(
        client.get(packet_path, headers=operator_headers),
        {409},
        "prove packet export is blocked before approval",
    )

    review_payload = {
        "decision": "APPROVED",
        "reviewer_label": "milestone-9-demo",
        "note": "Synthetic demo invoice and delivery source checked end to end.",
    }
    review = _expect(
        client.post(review_path, json=review_payload, headers=operator_headers),
        {201},
        "approve demonstration draft",
    ).json()
    retry = _expect(
        client.post(review_path, json=review_payload, headers=operator_headers),
        {200},
        "retry identical immutable review",
    ).json()
    if retry != review:
        raise LiveDemoError("the identical review retry did not return the stored review")

    stored_review = _expect(
        client.get(review_path.removesuffix("s"), headers=operator_headers),
        {200},
        "read stored review",
    ).json()
    if stored_review != review:
        raise LiveDemoError("the stored review does not match the approved review")

    packet = _expect(
        client.get(packet_path, headers=operator_headers),
        {200},
        "download approved evidence packet",
    )
    repeated_packet = _expect(
        client.get(packet_path, headers=operator_headers),
        {200},
        "repeat evidence packet download",
    )
    packet_sha256 = hashlib.sha256(packet.content).hexdigest()
    if repeated_packet.content != packet.content:
        raise LiveDemoError("repeated packet bytes are not deterministic")
    if packet.headers.get("x-proofshield-packet-sha256") != packet_sha256:
        raise LiveDemoError("packet response hash does not match the downloaded bytes")

    manifest_sha256, archive_names = _verify_packet(packet.content, draft)
    if packet.headers.get("x-proofshield-manifest-sha256") != manifest_sha256:
        raise LiveDemoError("manifest response hash does not match the packet manifest")

    history = _expect(
        client.get(f"{case_path}/history"),
        {200},
        "read append-only case history",
    ).json()
    actions = [entry["action"] for entry in history]
    if actions.count("DRAFT_APPROVED") != 1:
        raise LiveDemoError("expected exactly one DRAFT_APPROVED history action")

    return {
        "assessment_decision": assessment["decision"],
        "case_created_status": 201,
        "case_dispute_id": created["dispute_id"],
        "demo_label": normalized_label,
        "draft_id": draft["draft_id"],
        "evidence_file_count": 2,
        "history_actions": actions,
        "manifest_sha256": manifest_sha256,
        "packet_archive_entries": archive_names,
        "packet_sha256": packet_sha256,
        "packet_stable_on_retry": True,
        "review_decision": review["decision"],
        "review_id": review["review_id"],
        "review_retry_idempotent": True,
        "synthetic_demo_data_retained": True,
        "unauthorized_review_blocked": True,
        "unapproved_packet_blocked": True,
    }


def _demo_case(label: str, now: datetime) -> DisputeCase:
    order_id = f"demo_order_{label}"
    payment_id = f"demo_pay_{label}"
    amount = Decimal("4999.00")
    return DisputeCase(
        dispute_id=f"demo_disp_{label}",
        reason=DisputeReason.PRODUCT_NOT_RECEIVED,
        payment_id=payment_id,
        order_id=order_id,
        disputed_amount=amount,
        currency="INR",
        created_at=now,
        respond_by=now + timedelta(days=7),
        payment=PaymentRecord(
            payment_id=payment_id,
            order_id=order_id,
            amount=amount,
            currency="INR",
            captured=True,
        ),
        evidence=[],
    )


def _normalize_label(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    if not normalized:
        raise LiveDemoError("the demo label must contain a letter or number")
    return normalized[:48]


def _verify_packet(content: bytes, draft: dict[str, Any]) -> tuple[str, list[str]]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = sorted(archive.namelist())
        required = {
            "case.json",
            "draft.json",
            "evidence/E1_proofshield-demo-invoice.pdf",
            "evidence/E2_proofshield-demo-delivery.json",
            "manifest.json",
            "response.txt",
            "review.json",
        }
        if not required.issubset(names):
            raise LiveDemoError("the evidence packet is missing required entries")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest["review_decision"] != "APPROVED":
            raise LiveDemoError("the packet manifest is not approved")
        if manifest["draft_content_sha256"] != draft["content_sha256"]:
            raise LiveDemoError("the packet references a different draft hash")
        for entry in manifest["evidence"]:
            actual = hashlib.sha256(archive.read(entry["packet_path"])).hexdigest()
            if actual != entry["sha256"]:
                raise LiveDemoError(
                    f"packet evidence {entry['packet_path']} failed its SHA-256 check"
                )
        return manifest["manifest_sha256"], names


def _expect(response: Any, expected: set[int], action: str) -> Any:
    if response.status_code in expected:
        return response
    try:
        payload = response.json()
    except Exception:
        payload = response.text
    raise LiveDemoError(
        f"failed to {action}: HTTP {response.status_code}; response={payload}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm-live-write",
        action="store_true",
        help="Required acknowledgement that the script retains labelled synthetic data.",
    )
    parser.add_argument(
        "--project-ref",
        required=True,
        help="Must exactly match the configured ProofShield project reference.",
    )
    parser.add_argument(
        "--label",
        default=f"m9_{datetime.now(UTC):%Y%m%d_%H%M%S}",
        help="Label embedded in all synthetic case identifiers.",
    )
    arguments = parser.parse_args()
    if not arguments.confirm_live_write:
        parser.error("--confirm-live-write is required because demo data is retained")

    settings = SupabaseSettings.from_env()
    if settings.project_ref != EXPECTED_PROJECT_REF:
        raise LiveDemoError("the configured environment is not the ProofShield project")
    if arguments.project_ref != settings.project_ref:
        raise LiveDemoError("--project-ref does not match the configured environment")
    operator_secret = os.getenv("PROOFSHIELD_OPERATOR_SECRET", "")

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        result = run_demo(
            client,
            operator_secret=operator_secret,
            label=arguments.label,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
