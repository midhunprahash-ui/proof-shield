from pathlib import Path

from proofshield.domain import EvidenceType
from proofshield.extraction import ExtractionField
from proofshield.extraction_evaluation import (
    LabelledExtractionCase,
    evaluate_extractor,
    load_cases,
)

FIXTURES = Path("data/synthetic/extraction_cases.jsonl")


def test_frozen_deterministic_baseline_is_exact() -> None:
    result = evaluate_extractor(load_cases(FIXTURES))

    assert result.cases == 6
    assert result.expected_fields == 18
    assert result.proposed_fields == 18
    assert result.correct_fields == 18
    assert result.field_precision == 1
    assert result.field_recall == 1
    assert result.exact_case_accuracy == 1
    assert result.errors == []


def test_evaluation_reports_field_level_errors() -> None:
    case = LabelledExtractionCase(
        scenario="expected_mismatch",
        evidence_type=EvidenceType.INVOICE,
        content_type="text/plain",
        content="Order ID: actual_order",
        expected={ExtractionField.ORDER_ID: "expected_order"},
    )

    result = evaluate_extractor([case])

    assert result.correct_fields == 0
    assert result.field_precision == 0
    assert result.field_recall == 0
    assert result.exact_case_accuracy == 0
    assert result.errors[0].model_dump() == {
        "scenario": "expected_mismatch",
        "field": ExtractionField.ORDER_ID,
        "expected": "expected_order",
        "proposed": "actual_order",
    }
