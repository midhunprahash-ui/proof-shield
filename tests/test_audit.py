from proofshield.audit import AuditStatus, ClaimResult
from proofshield.domain import Decision
from proofshield.memory import InMemoryEventLedger


def test_completed_event_is_idempotent() -> None:
    ledger = InMemoryEventLedger()

    assert ledger.claim("event_1", "digest_1", event_type="payment.dispute.created") == (
        ClaimResult.CLAIMED
    )
    ledger.finish(
        "event_1",
        "digest_1",
        status=AuditStatus.PROCESSED,
        event_type="payment.dispute.created",
        dispute_id="disp_1",
        decision=Decision.INSUFFICIENT_EVIDENCE,
        detail="Processed in test.",
    )

    assert ledger.claim(
        "event_1", "digest_1", event_type="payment.dispute.created"
    ) == ClaimResult.DUPLICATE
    assert [entry.status for entry in ledger.entries()] == [
        AuditStatus.RECEIVED,
        AuditStatus.PROCESSED,
        AuditStatus.DUPLICATE,
    ]


def test_reused_event_id_with_different_body_is_rejected() -> None:
    ledger = InMemoryEventLedger()
    ledger.claim("event_1", "digest_1", event_type="payment.dispute.created")

    result = ledger.claim("event_1", "different", event_type="payment.dispute.created")

    assert result == ClaimResult.CONFLICT
    assert ledger.entries()[-1].status == AuditStatus.REJECTED


def test_failed_event_can_be_retried() -> None:
    ledger = InMemoryEventLedger()
    ledger.claim("event_1", "digest_1", event_type="payment.dispute.created")
    ledger.fail(
        "event_1",
        "digest_1",
        event_type="payment.dispute.created",
        detail="Temporary parsing failure.",
    )

    assert ledger.claim("event_1", "digest_1", event_type="payment.dispute.created") == (
        ClaimResult.CLAIMED
    )
