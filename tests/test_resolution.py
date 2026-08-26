from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from proofshield.consistency import ConsistencyStatus, EvidenceConsistencyAnalyzer
from proofshield.domain import Decision, EvidenceDocument, EvidenceType
from proofshield.memory import InMemoryCaseRepository
from proofshield.resolution import (
    EvidenceResolutionAction,
    EvidenceResolutionError,
    EvidenceResolutionRequest,
    create_evidence_resolution,
)
from proofshield.synthetic import make_case
from proofshield.verifier import CaseAssessor

OPERATOR_ID = UUID("00000000-0000-4000-8000-000000000001")
RESOLVED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


def _request(
    evidence_id: str,
    *,
    action: EvidenceResolutionAction = EvidenceResolutionAction.EXCLUDED_INCORRECT,
    replacement_evidence_id: str | None = None,
) -> EvidenceResolutionRequest:
    return EvidenceResolutionRequest(
        evidence_id=evidence_id,
        action=action,
        replacement_evidence_id=replacement_evidence_id,
        reason="Operator verified that this source was attached incorrectly.",
    )


def test_excluded_incorrect_evidence_no_longer_affects_analysis() -> None:
    case = make_case(1, "valid_delivery")
    case.evidence.append(
        EvidenceDocument(
            evidence_id="invoice_wrong_order",
            evidence_type=EvidenceType.INVOICE,
            source_verified=True,
            order_id="order_from_another_purchase",
            payment_id=case.payment_id,
            amount=case.disputed_amount,
        )
    )
    before = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)
    resolution = create_evidence_resolution(
        case,
        [],
        _request("invoice_wrong_order"),
        resolved_by=OPERATOR_ID,
        created_at=RESOLVED_AT,
    )

    report = EvidenceConsistencyAnalyzer().analyze(case, [resolution])
    after = CaseAssessor().assess(
        case,
        [resolution],
        evaluated_at=EVALUATED_AT,
    )

    assert before.decision == Decision.NEEDS_REVIEW
    assert report.status == ConsistencyStatus.CONSISTENT
    assert report.resolution_count == 1
    assert report.excluded_evidence_ids == ["invoice_wrong_order"]
    assert "invoice_wrong_order" not in report.active_evidence_ids
    assert after.decision == Decision.SAFE_TO_DRAFT


def test_excluding_only_required_evidence_makes_case_incomplete() -> None:
    case = make_case(2, "valid_delivery")
    resolution = create_evidence_resolution(
        case,
        [],
        _request("invoice_0002"),
        resolved_by=OPERATOR_ID,
        created_at=RESOLVED_AT,
    )

    report = EvidenceConsistencyAnalyzer().analyze(case, [resolution])
    assessment = CaseAssessor().assess(
        case,
        [resolution],
        evaluated_at=EVALUATED_AT,
    )

    assert report.status == ConsistencyStatus.INCOMPLETE
    assert assessment.decision == Decision.INSUFFICIENT_EVIDENCE


def test_superseded_resolution_requires_active_same_type_replacement() -> None:
    case = make_case(3, "valid_delivery")
    replacement = case.evidence[0].model_copy(
        update={"evidence_id": "invoice_replacement"},
        deep=True,
    )
    case.evidence.append(replacement)

    resolution = create_evidence_resolution(
        case,
        [],
        _request(
            "invoice_0003",
            action=EvidenceResolutionAction.SUPERSEDED,
            replacement_evidence_id="invoice_replacement",
        ),
        resolved_by=OPERATOR_ID,
        created_at=RESOLVED_AT,
    )

    assert resolution.replacement_evidence_id == "invoice_replacement"
    assert EvidenceConsistencyAnalyzer().analyze(case, [resolution]).status == (
        ConsistencyStatus.CONSISTENT
    )

    with pytest.raises(EvidenceResolutionError, match="same evidence type"):
        create_evidence_resolution(
            case,
            [],
            _request(
                "invoice_0003",
                action=EvidenceResolutionAction.SUPERSEDED,
                replacement_evidence_id="delivery_0003",
            ),
            resolved_by=OPERATOR_ID,
            created_at=RESOLVED_AT,
        )


def test_resolution_is_idempotent_but_cannot_be_changed_or_chained() -> None:
    case = make_case(4, "valid_delivery")
    replacement = case.evidence[0].model_copy(
        update={"evidence_id": "invoice_replacement"},
        deep=True,
    )
    case.evidence.append(replacement)
    request = _request(
        "invoice_0004",
        action=EvidenceResolutionAction.SUPERSEDED,
        replacement_evidence_id="invoice_replacement",
    )
    resolution = create_evidence_resolution(
        case,
        [],
        request,
        resolved_by=OPERATOR_ID,
        created_at=RESOLVED_AT,
    )

    retry = create_evidence_resolution(
        case,
        [resolution],
        request,
        resolved_by=OPERATOR_ID,
        created_at=datetime(2026, 8, 24, 14, 0, tzinfo=UTC),
    )

    assert retry == resolution
    with pytest.raises(EvidenceResolutionError, match="immutable"):
        create_evidence_resolution(
            case,
            [resolution],
            _request("invoice_0004"),
            resolved_by=OPERATOR_ID,
        )
    with pytest.raises(EvidenceResolutionError, match="used as a replacement"):
        create_evidence_resolution(
            case,
            [resolution],
            _request("invoice_replacement"),
            resolved_by=OPERATOR_ID,
        )


def test_repository_appends_resolution_history_without_removing_evidence() -> None:
    case = make_case(5, "valid_delivery")
    repository = InMemoryCaseRepository()
    repository.save_case(case, source="test", owner_id=str(OPERATOR_ID))
    for document in case.evidence:
        repository.add_evidence(case.dispute_id, document)
    resolution = create_evidence_resolution(
        case,
        [],
        _request("message_0005"),
        resolved_by=OPERATOR_ID,
        created_at=RESOLVED_AT,
    )

    assert repository.save_evidence_resolution(resolution) is True
    assert repository.save_evidence_resolution(resolution) is False
    assert len(repository.get_case(case.dispute_id).evidence) == 3
    assert repository.list_evidence_resolutions(case.dispute_id) == [resolution]
    assert repository.get_history(case.dispute_id)[-1].action == "EVIDENCE_RESOLVED"


def test_resolution_reason_is_trimmed_before_length_validation() -> None:
    with pytest.raises(ValidationError, match="at least 10 characters"):
        EvidenceResolutionRequest(
            evidence_id="invoice_1",
            action=EvidenceResolutionAction.EXCLUDED_INCORRECT,
            reason="          no          ",
        )
