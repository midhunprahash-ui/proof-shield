from proofshield.audit import AuditStatus, ClaimResult, LocalEventLedger
from proofshield.domain import Decision


def test_completed_event_is_idempotent_across_restart(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    ledger = LocalEventLedger(path)

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

    restarted_ledger = LocalEventLedger(path)
    assert restarted_ledger.claim(
        "event_1", "digest_1", event_type="payment.dispute.created"
    ) == ClaimResult.DUPLICATE
    assert [entry.status for entry in restarted_ledger.entries()] == [
        AuditStatus.RECEIVED,
        AuditStatus.PROCESSED,
        AuditStatus.DUPLICATE,
    ]


def test_reused_event_id_with_different_body_is_rejected(tmp_path) -> None:
    ledger = LocalEventLedger(tmp_path / "audit.jsonl")
    ledger.claim("event_1", "digest_1", event_type="payment.dispute.created")

    result = ledger.claim("event_1", "different", event_type="payment.dispute.created")

    assert result == ClaimResult.CONFLICT
    assert ledger.entries()[-1].status == AuditStatus.REJECTED


def test_failed_event_can_be_retried(tmp_path) -> None:
    ledger = LocalEventLedger(tmp_path / "audit.jsonl")
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
