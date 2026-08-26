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
from tests.auth_helpers import TEST_ACCESS_TOKEN, TEST_AUTHENTICATOR


def test_guarded_demo_verifies_the_complete_human_approved_flow() -> None:
    client = TestClient(
        create_app(
            operator_authenticator=TEST_AUTHENTICATOR,
            case_repository=InMemoryCaseRepository(),
            evidence_file_store=InMemoryEvidenceFileStore(),
            webhook_ledger=InMemoryEventLedger(),
        )
    )

    result = run_demo(
        client,
        access_token=TEST_ACCESS_TOKEN,
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


def test_demo_rejects_a_missing_access_token_before_writing() -> None:
    with pytest.raises(LiveDemoError, match="access token"):
        run_demo(
            TestClient(
                create_app(
                    operator_authenticator=TEST_AUTHENTICATOR,
                    case_repository=InMemoryCaseRepository(),
                    evidence_file_store=InMemoryEvidenceFileStore(),
                    webhook_ledger=InMemoryEventLedger(),
                )
            ),
            access_token="too-short",
            label="must-not-write",
        )
