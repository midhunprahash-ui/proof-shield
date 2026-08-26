import json

import pytest

from proofshield.extraction import RoutingEvidenceExtractor
from proofshield.ocr import OcrTextObservation
from proofshield.ocr_evaluation import evaluate_ocr_extractor, load_ocr_cases


class EvaluationOcrProvider:
    name = "evaluation-ocr"

    def read(self, content: bytes, *, content_type: str) -> list[OcrTextObservation]:
        del content, content_type
        return [
            OcrTextObservation(
                page=1,
                text="Order ID: order_eval_1",
                confidence=0.99,
                bounding_box=(10, 20, 250, 50),
            )
        ]


def test_ocr_evaluation_scores_frozen_source_files(tmp_path) -> None:
    (tmp_path / "invoice.png").write_bytes(b"synthetic scan")
    manifest = tmp_path / "ocr_cases.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "scenario": "synthetic_invoice",
                "evidence_type": "INVOICE",
                "content_type": "image/png",
                "source_file": "invoice.png",
                "expected": {"order_id": "order_eval_1"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate_ocr_extractor(
        load_ocr_cases(manifest),
        RoutingEvidenceExtractor(EvaluationOcrProvider()),
    )

    assert result.extractor == "evaluation-ocr+labelled-fields-v1"
    assert result.cases == 1
    assert result.field_precision == 1
    assert result.field_recall == 1
    assert result.exact_case_accuracy == 1


def test_ocr_manifest_cannot_read_outside_its_directory(tmp_path) -> None:
    manifest_directory = tmp_path / "manifest"
    manifest_directory.mkdir()
    (tmp_path / "outside.png").write_bytes(b"outside")
    manifest = manifest_directory / "ocr_cases.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "scenario": "escape_attempt",
                "evidence_type": "INVOICE",
                "content_type": "image/png",
                "source_file": "../outside.png",
                "expected": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="escapes"):
        load_ocr_cases(manifest)
