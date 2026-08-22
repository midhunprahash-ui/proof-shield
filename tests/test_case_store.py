from decimal import Decimal

import pytest

from proofshield.case_store import (
    CaseConflictError,
    CaseHistoryAction,
    CaseNotFoundError,
    EvidenceConflictError,
)
from proofshield.domain import EvidenceDocument, EvidenceType
from proofshield.memory import InMemoryCaseRepository
from proofshield.synthetic import make_case


def empty_case(index: int):
    return make_case(index, "valid_delivery").model_copy(update={"evidence": []})


def invoice(case, *, evidence_id: str = "invoice_1") -> EvidenceDocument:
    return EvidenceDocument(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.INVOICE,
        source_name="invoice.pdf",
        reviewed_by_human=True,
        source_verified=True,
        order_id=case.order_id,
        payment_id=case.payment_id,
        amount=case.disputed_amount,
    )


def test_case_and_evidence_round_trip() -> None:
    repository = InMemoryCaseRepository()
    case = empty_case(1)

    assert repository.save_case(case, source="test") is True
    assert repository.add_evidence(case.dispute_id, invoice(case)) is True

    stored = repository.get_case(case.dispute_id)
    assert stored.model_dump() == case.model_copy(
        update={"evidence": [invoice(case)]}
    ).model_dump()
    assert repository.list_cases()[0].evidence_count == 1


def test_same_core_case_is_idempotent_but_changed_facts_conflict() -> None:
    repository = InMemoryCaseRepository()
    case = empty_case(2)
    repository.save_case(case, source="first")

    assert repository.save_case(case, source="retry") is False

    changed_case = case.model_copy(update={"disputed_amount": Decimal("9999")})
    with pytest.raises(CaseConflictError, match="different core facts"):
        repository.save_case(changed_case, source="conflict")


def test_evidence_id_cannot_move_between_cases() -> None:
    repository = InMemoryCaseRepository()
    first = empty_case(3)
    second = empty_case(4)
    repository.save_case(first, source="test")
    repository.save_case(second, source="test")
    repository.add_evidence(first.dispute_id, invoice(first, evidence_id="shared"))

    with pytest.raises(EvidenceConflictError, match="already attached elsewhere"):
        repository.add_evidence(
            second.dispute_id,
            invoice(second, evidence_id="shared"),
        )


def test_case_history_is_append_only_and_ordered() -> None:
    repository = InMemoryCaseRepository()
    case = empty_case(5)
    repository.save_case(case, source="test")
    repository.add_evidence(case.dispute_id, invoice(case))

    history = repository.get_history(case.dispute_id)

    assert [entry.action for entry in history] == [
        CaseHistoryAction.CASE_CREATED,
        CaseHistoryAction.EVIDENCE_ADDED,
    ]
    assert history[0].sequence < history[1].sequence


def test_unknown_case_is_rejected() -> None:
    repository = InMemoryCaseRepository()

    with pytest.raises(CaseNotFoundError):
        repository.get_case("missing")
