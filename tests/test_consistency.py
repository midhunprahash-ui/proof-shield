from proofshield.consistency import (
    ConsistencyStatus,
    EvidenceConsistencyAnalyzer,
    FactOutcome,
    RequirementOutcome,
)
from proofshield.domain import EvidenceDocument, EvidenceType
from proofshield.synthetic import make_case


def fact(report, field: str):
    return next(item for item in report.facts if item.field == field)


def requirement(report, evidence_type: EvidenceType):
    return next(
        item for item in report.requirements if item.evidence_type == evidence_type
    )


def test_matching_verified_sources_are_reported_as_consistent() -> None:
    report = EvidenceConsistencyAnalyzer().analyze(make_case(1, "valid_delivery"))

    assert report.status == ConsistencyStatus.CONSISTENT
    assert report.conflict_count == 0
    assert report.missing_count == 0
    assert report.unverified_count == 0
    assert report.advisory_only is True
    assert report.human_review_required is True
    assert fact(report, "order_id").outcome == FactOutcome.MATCH
    assert len(fact(report, "order_id").observations) == 3


def test_optional_customer_message_does_not_make_report_incomplete() -> None:
    report = EvidenceConsistencyAnalyzer().analyze(
        make_case(2, "valid_delivery_without_customer_message")
    )

    assert report.status == ConsistencyStatus.CONSISTENT
    customer = requirement(report, EvidenceType.CUSTOMER_COMMUNICATION)
    assert customer.required is False
    assert customer.outcome == RequirementOutcome.OPTIONAL
    assert all(item.field != "customer_acknowledged_delivery" for item in report.facts)


def test_missing_required_source_and_facts_are_named() -> None:
    report = EvidenceConsistencyAnalyzer().analyze(
        make_case(3, "missing_delivery_proof")
    )

    assert report.status == ConsistencyStatus.INCOMPLETE
    assert requirement(
        report, EvidenceType.DELIVERY_PROOF
    ).outcome == RequirementOutcome.MISSING
    assert fact(report, "delivery_status").outcome == FactOutcome.MISSING
    assert report.missing_count >= 2


def test_later_conflicting_source_is_not_hidden_by_the_first_source() -> None:
    case = make_case(4, "valid_delivery")
    case.evidence.append(
        EvidenceDocument(
            evidence_id="invoice_conflict",
            evidence_type=EvidenceType.INVOICE,
            source_name="second-invoice.pdf",
            source_verified=True,
            order_id="order_from_another_purchase",
            payment_id=case.payment_id,
            amount=case.disputed_amount,
        )
    )

    report = EvidenceConsistencyAnalyzer().analyze(case)
    order = fact(report, "order_id")

    assert report.status == ConsistencyStatus.CONFLICTS_FOUND
    assert report.conflict_count == 1
    assert order.outcome == FactOutcome.CONFLICT
    assert {item.evidence_id for item in order.observations} == {
        "invoice_0004",
        "delivery_0004",
        "message_0004",
        "invoice_conflict",
    }
    conflict = next(
        item for item in order.observations if item.evidence_id == "invoice_conflict"
    )
    assert conflict.matches_expected is False
    assert conflict.source_name == "second-invoice.pdf"


def test_matching_values_from_unverified_source_still_require_review() -> None:
    report = EvidenceConsistencyAnalyzer().analyze(
        make_case(5, "unverified_delivery_source")
    )

    assert report.status == ConsistencyStatus.UNVERIFIED_SOURCES
    assert report.unverified_count == 1
    assert requirement(
        report, EvidenceType.DELIVERY_PROOF
    ).outcome == RequirementOutcome.UNVERIFIED
    assert fact(report, "delivery_status").outcome == FactOutcome.UNVERIFIED


def test_optional_sources_that_disagree_are_still_surfaced() -> None:
    case = make_case(6, "valid_delivery")
    case.evidence.append(
        EvidenceDocument(
            evidence_id="message_denial",
            evidence_type=EvidenceType.CUSTOMER_COMMUNICATION,
            source_verified=True,
            customer_acknowledged_delivery=False,
        )
    )

    report = EvidenceConsistencyAnalyzer().analyze(case)

    assert report.status == ConsistencyStatus.CONFLICTS_FOUND
    assert (
        fact(report, "customer_acknowledged_delivery").outcome
        == FactOutcome.CONFLICT
    )
