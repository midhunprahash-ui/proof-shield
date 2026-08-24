from datetime import UTC, datetime, timedelta

import pytest

from proofshield.domain import Decision, DisputeReason
from proofshield.synthetic import SCENARIOS, generate_cases, make_case
from proofshield.verifier import CaseAssessor

EVALUATED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(("scenario", "expected_decision"), SCENARIOS)
def test_documented_scenarios(scenario: str, expected_decision: Decision) -> None:
    case = make_case(1, scenario)

    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    assert assessment.decision == expected_decision
    assert assessment.human_approval_required is True


def test_unsupported_reason_is_not_drafted() -> None:
    case = make_case(2, "valid_delivery")
    case.reason = DisputeReason.OTHER

    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    assert assessment.decision == Decision.INSUFFICIENT_EVIDENCE
    assert "UNSUPPORTED_REASON" in {check.code for check in assessment.checks}


def test_near_deadline_warns_but_does_not_override_valid_evidence() -> None:
    case = make_case(3, "valid_delivery")
    case.respond_by = EVALUATED_AT + timedelta(hours=12)

    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    assert assessment.decision == Decision.SAFE_TO_DRAFT
    assert "DEADLINE_NEAR" in {check.code for check in assessment.checks}


def test_naive_evaluation_time_is_rejected() -> None:
    case = make_case(4, "valid_delivery")

    with pytest.raises(ValueError, match="timezone"):
        CaseAssessor().assess(case, evaluated_at=datetime(2026, 8, 22, 12, 0))


def test_generated_development_cases_match_their_documented_scenarios() -> None:
    assessor = CaseAssessor()

    for labelled_case in generate_cases(60):
        assessment = assessor.assess(
            labelled_case.case,
            evaluated_at=labelled_case.case.created_at + timedelta(hours=2),
        )
        assert assessment.decision == labelled_case.expected_decision
