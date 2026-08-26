"""Evaluate a configured OCR provider on frozen, synthetic scan files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from proofshield.domain import EvidenceType
from proofshield.extraction import (
    EvidenceExtractor,
    ExtractionField,
    build_configured_evidence_extractor,
)
from proofshield.extraction_evaluation import (
    ExtractionErrorExample,
    ExtractionEvaluation,
)


class OcrEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = Field(min_length=1, max_length=200)
    evidence_type: EvidenceType
    content_type: Literal["application/pdf", "image/jpeg", "image/png"]
    source_file: str = Field(min_length=1, max_length=500)
    expected: dict[ExtractionField, str | bool]


def load_ocr_cases(path: Path) -> list[tuple[OcrEvaluationCase, bytes]]:
    manifest_path = path.resolve()
    manifest_directory = manifest_path.parent
    cases: list[tuple[OcrEvaluationCase, bytes]] = []
    for line_number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
        if not line.strip():
            continue
        try:
            case = OcrEvaluationCase.model_validate_json(line)
        except Exception as error:
            raise ValueError(f"invalid OCR fixture at line {line_number}") from error
        source_path = (manifest_directory / case.source_file).resolve()
        if not source_path.is_relative_to(manifest_directory):
            raise ValueError(f"OCR fixture at line {line_number} escapes its manifest directory")
        try:
            content = source_path.read_bytes()
        except OSError as error:
            raise ValueError(
                f"OCR fixture source is unavailable at line {line_number}: {case.source_file}"
            ) from error
        cases.append((case, content))
    if not cases:
        raise ValueError("OCR fixture manifest must contain at least one case")
    return cases


def evaluate_ocr_extractor(
    cases: list[tuple[OcrEvaluationCase, bytes]],
    extractor: EvidenceExtractor | None = None,
) -> ExtractionEvaluation:
    configured = extractor or build_configured_evidence_extractor()
    expected_total = 0
    proposed_total = 0
    correct_total = 0
    exact_cases = 0
    errors: list[ExtractionErrorExample] = []
    extractor_names: set[str] = set()

    for index, (case, content) in enumerate(cases, 1):
        proposal = configured.extract(
            content,
            content_type=case.content_type,
            evidence_type=case.evidence_type,
            source_file_id=f"ocr_fixture_{index}",
            source_sha256=hashlib.sha256(content).hexdigest(),
        )
        extractor_names.add(proposal.extractor)
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
        extractor=", ".join(sorted(extractor_names)),
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
        description="Evaluate the configured OCR provider on frozen synthetic scans."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/synthetic/ocr/ocr_cases.jsonl"),
    )
    args = parser.parse_args()
    result = evaluate_ocr_extractor(load_ocr_cases(args.input))
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
