"""Reproducible evaluation for evidence extraction providers."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofshield.domain import EvidenceType
from proofshield.extraction import (
    DeterministicEvidenceExtractor,
    EvidenceExtractor,
    ExtractionField,
)


class LabelledExtractionCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=200)
    evidence_type: EvidenceType
    content_type: Literal["application/json", "text/plain"]
    content: str
    expected: dict[ExtractionField, str | bool]


class ExtractionErrorExample(BaseModel):
    scenario: str
    field: ExtractionField
    expected: str | bool | None
    proposed: str | bool | None


class ExtractionEvaluation(BaseModel):
    extractor: str
    cases: int
    expected_fields: int
    proposed_fields: int
    correct_fields: int
    field_precision: float = Field(ge=0, le=1)
    field_recall: float = Field(ge=0, le=1)
    exact_case_accuracy: float = Field(ge=0, le=1)
    errors: list[ExtractionErrorExample]


def load_cases(path: Path) -> list[LabelledExtractionCase]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(LabelledExtractionCase.model_validate_json(line))
        except Exception as error:
            raise ValueError(f"invalid extraction fixture at line {line_number}") from error
    if not cases:
        raise ValueError("extraction fixture must contain at least one case")
    return cases


def evaluate_extractor(
    cases: list[LabelledExtractionCase],
    extractor: EvidenceExtractor | None = None,
) -> ExtractionEvaluation:
    configured = extractor or DeterministicEvidenceExtractor()
    expected_total = 0
    proposed_total = 0
    correct_total = 0
    exact_cases = 0
    errors = []

    for index, case in enumerate(cases, 1):
        content = case.content.encode("utf-8")
        proposal = configured.extract(
            content,
            content_type=case.content_type,
            evidence_type=case.evidence_type,
            source_file_id=f"fixture_{index}",
            source_sha256=hashlib.sha256(content).hexdigest(),
        )
        proposed = {claim.field: claim.value for claim in proposal.claims}
        expected_total += len(case.expected)
        proposed_total += len(proposed)
        correct_total += sum(
            proposed.get(field) == value for field, value in case.expected.items()
        )
        if proposed == case.expected:
            exact_cases += 1
        for field in sorted(set(case.expected) | set(proposed), key=str):
            expected_value = case.expected.get(field)
            proposed_value = proposed.get(field)
            if expected_value != proposed_value:
                errors.append(
                    ExtractionErrorExample(
                        scenario=case.scenario,
                        field=field,
                        expected=expected_value,
                        proposed=proposed_value,
                    )
                )

    return ExtractionEvaluation(
        extractor=getattr(configured, "name", configured.__class__.__name__),
        cases=len(cases),
        expected_fields=expected_total,
        proposed_fields=proposed_total,
        correct_fields=correct_total,
        field_precision=correct_total / proposed_total if proposed_total else 0,
        field_recall=correct_total / expected_total if expected_total else 0,
        exact_case_accuracy=exact_cases / len(cases),
        errors=errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the deterministic evidence extractor on frozen fixtures."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/synthetic/extraction_cases.jsonl"),
    )
    args = parser.parse_args()
    result = evaluate_extractor(load_cases(args.input))
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
