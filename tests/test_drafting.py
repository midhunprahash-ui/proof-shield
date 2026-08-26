from datetime import UTC, datetime, timedelta

import pytest

from proofshield.domain import Decision, EvidenceDocument, EvidenceType
from proofshield.drafting import (
    DraftGenerationError,
    DraftStatus,
    EvidenceGroundedDraftGenerator,
)
from proofshield.synthetic import make_case
from proofshield.verifier import CaseAssessor

EVALUATED_AT = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def file_backed_case(index: int = 1):
    case = make_case(index, "valid_delivery_without_customer_message")
    evidence = []
    for document in case.evidence:
        suffix = "invoice" if document.evidence_type == EvidenceType.INVOICE else "delivery"
        evidence.append(
            document.model_copy(
                update={
                    "source_file_id": f"file_{suffix}",
                    "source_name": f"{suffix}.json",
                    "source_sha256": ("a" if suffix == "invoice" else "b") * 64,
                    "reviewed_by_human": True,
                    "source_verified": True,
                }
            )
        )
    return case.model_copy(update={"evidence": evidence})


def test_safe_case_generates_grounded_pending_draft() -> None:
    case = file_backed_case()
    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    draft = EvidenceGroundedDraftGenerator().generate(
        case,
        assessment,
        created_at=EVALUATED_AT,
    )

    assert draft.decision == Decision.SAFE_TO_DRAFT
    assert draft.status == DraftStatus.PENDING_HUMAN_APPROVAL
    assert draft.human_approval_required is True
    assert [citation.label for citation in draft.citations] == ["E1", "E2"]
    assert {citation.source_file_id for citation in draft.citations} == {
        "file_invoice",
        "file_delivery",
    }
    assert "[E1]" in draft.body
    assert "[E2]" in draft.body
    assert "has not been submitted" in draft.body


def test_generation_is_idempotent_for_the_same_case_state() -> None:
    case = file_backed_case(2)
    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)
    generator = EvidenceGroundedDraftGenerator()

    first = generator.generate(case, assessment, created_at=EVALUATED_AT)
    second = generator.generate(
        case,
        assessment,
        created_at=EVALUATED_AT + timedelta(minutes=10),
    )

    assert first.draft_id == second.draft_id
    assert first.input_sha256 == second.input_sha256
    assert first.content_sha256 == second.content_sha256


@pytest.mark.parametrize("scenario", ["missing_delivery_proof", "order_mismatch"])
def test_non_safe_decisions_refuse_to_draft(scenario: str) -> None:
    case = make_case(3, scenario)
    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    with pytest.raises(DraftGenerationError, match="only SAFE_TO_DRAFT"):
        EvidenceGroundedDraftGenerator().generate(case, assessment)


def test_safe_but_non_file_backed_evidence_refuses_to_draft() -> None:
    case = make_case(4, "valid_delivery_without_customer_message")
    case = case.model_copy(
        update={
            "evidence": [
                document.model_copy(update={"reviewed_by_human": True})
                for document in case.evidence
            ]
        }
    )
    assessment = CaseAssessor().assess(case, evaluated_at=EVALUATED_AT)

    assert assessment.decision == Decision.SAFE_TO_DRAFT
    with pytest.raises(DraftGenerationError, match="uploaded file with a hash"):
        EvidenceGroundedDraftGenerator().generate(case, assessment)


def test_draft_input_fingerprint_changes_when_matching_evidence_is_added() -> None:
    case = file_backed_case(5)
    assessor = CaseAssessor()
    generator = EvidenceGroundedDraftGenerator()
    first_assessment = assessor.assess(case, evaluated_at=EVALUATED_AT)
    first_fingerprint = generator.input_sha256(case, first_assessment)
    case.evidence.append(
        EvidenceDocument(
            evidence_id="invoice_additional_match",
            evidence_type=EvidenceType.INVOICE,
            source_verified=True,
            reviewed_by_human=True,
            order_id=case.order_id,
            payment_id=case.payment_id,
            amount=case.disputed_amount,
        )
    )
    second_assessment = assessor.assess(case, evaluated_at=EVALUATED_AT)

    assert second_assessment.decision == Decision.SAFE_TO_DRAFT
    assert generator.input_sha256(case, second_assessment) != first_fingerprint
