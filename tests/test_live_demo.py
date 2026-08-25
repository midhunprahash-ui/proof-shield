from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from proofshield.api import create_app
from proofshield.memory import (
    InMemoryCaseRepository,
    InMemoryEventLedger,
    InMemoryEvidenceFileStore,
)
from scripts.run_live_demo import LiveDemoError, run_demo

OPERATOR_SECRET = "test-operator-secret-with-32-characters"


def test_guarded_demo_verifies_the_complete_human_approved_flow() -> None:
    client = TestClient(
        create_app(
            operator_secret=OPERATOR_SECRET,
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
        )
    )

    result = run_demo(
        client,
        operator_secret=OPERATOR_SECRET,
        label="unit-test",
        now=datetime(2026, 8, 25, 10, 0, tzinfo=UTC),
    )

    assert result["case_dispute_id"] == "demo_disp_unit_test"
    assert result["assessment_decision"] == "SAFE_TO_DRAFT"
    assert result["review_decision"] == "APPROVED"
    assert result["review_retry_idempotent"] is True
    assert result["packet_stable_on_retry"] is True
    assert result["unauthorized_review_blocked"] is True
    assert result["unapproved_packet_blocked"] is True
    assert result["history_actions"].count("DRAFT_APPROVED") == 1


def test_demo_rejects_a_short_operator_secret_before_writing() -> None:
    with pytest.raises(LiveDemoError, match="at least 32"):
        run_demo(
            TestClient(
                create_app(
                    case_repository=InMemoryCaseRepository(),
                    evidence_file_store=InMemoryEvidenceFileStore(),
                    webhook_ledger=InMemoryEventLedger(),
                )
            ),
            operator_secret="too-short",
            label="must-not-write",
        )
