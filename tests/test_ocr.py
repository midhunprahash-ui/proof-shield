from pathlib import Path

import pytest

from proofshield.ocr import OcrProcessingError, PaddleOcrProvider


class FakeResult:
    def __init__(self, payload: dict) -> None:
        self.json = payload


class FakePipeline:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.received_path: Path | None = None

    def predict_iter(self, source_path: str):
        self.received_path = Path(source_path)
        assert self.received_path.exists()
        yield from self.results


def result(*, page_index: int, text: str, score: float, box: list[int]) -> FakeResult:
    return FakeResult(
        {
            "res": {
                "page_index": page_index,
                "rec_texts": [text],
                "rec_scores": [score],
                "rec_boxes": [box],
            }
        }
    )


def test_paddle_adapter_returns_located_text_and_removes_temporary_source() -> None:
    pipeline = FakePipeline(
        [result(page_index=0, text="Order ID: order_12", score=0.97, box=[10, 20, 210, 45])]
    )
    provider = PaddleOcrProvider(pipeline_factory=lambda: pipeline)

    observations = provider.read(b"synthetic image", content_type="image/png")

    assert len(observations) == 1
    assert observations[0].page == 1
    assert observations[0].text == "Order ID: order_12"
    assert observations[0].source_reference == "page 1, box [10,20,210,45]"
    assert pipeline.received_path is not None
    assert not pipeline.received_path.exists()


def test_paddle_adapter_rejects_misaligned_provider_output() -> None:
    pipeline = FakePipeline(
        [
            FakeResult(
                {
                    "res": {
                        "page_index": 0,
                        "rec_texts": ["Order ID"],
                        "rec_scores": [],
                        "rec_boxes": [[1, 2, 3, 4]],
                    }
                }
            )
        ]
    )
    provider = PaddleOcrProvider(pipeline_factory=lambda: pipeline)

    with pytest.raises(OcrProcessingError, match="misaligned"):
        provider.read(b"synthetic image", content_type="image/jpeg")


def test_paddle_adapter_stops_documents_over_the_page_limit() -> None:
    pipeline = FakePipeline(
        [
            result(page_index=0, text="Page one", score=0.9, box=[1, 1, 20, 20]),
            result(page_index=1, text="Page two", score=0.9, box=[1, 1, 20, 20]),
        ]
    )
    provider = PaddleOcrProvider(max_pages=1, pipeline_factory=lambda: pipeline)

    with pytest.raises(OcrProcessingError, match="1-page"):
        provider.read(b"%PDF-1.4 synthetic", content_type="application/pdf")
