"""Replaceable document OCR providers for private evidence files."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

OCR_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})


class OcrProviderError(RuntimeError):
    """Base class for document-provider failures."""


class OcrProviderUnavailable(OcrProviderError):
    """Raised when the configured provider cannot run in this environment."""


class OcrProcessingError(OcrProviderError):
    """Raised when a provider cannot safely produce OCR observations."""


class OcrTextObservation(BaseModel):
    """One provider observation with enough location data for human review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=10_000)
    confidence: float = Field(ge=0, le=1)
    bounding_box: tuple[int, int, int, int]

    @model_validator(mode="after")
    def validate_box(self) -> OcrTextObservation:
        left, top, right, bottom = self.bounding_box
        if min(self.bounding_box) < 0 or right <= left or bottom <= top:
            raise ValueError("OCR bounding box must have positive area")
        return self

    @property
    def source_reference(self) -> str:
        left, top, right, bottom = self.bounding_box
        return f"page {self.page}, box [{left},{top},{right},{bottom}]"


class DocumentOcrProvider(Protocol):
    name: str

    def read(
        self,
        content: bytes,
        *,
        content_type: str,
    ) -> list[OcrTextObservation]: ...


class PaddleOcrProvider:
    """Lazy PP-OCRv6 adapter that runs locally after its model setup."""

    name = "paddleocr-pp-ocrv6-local-v1"

    def __init__(
        self,
        *,
        max_pages: int = 10,
        pipeline_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not 1 <= max_pages <= 50:
            raise ValueError("max_pages must be between 1 and 50")
        self.max_pages = max_pages
        self._pipeline_factory = pipeline_factory
        self._pipeline: Any | None = None
        self._lock = threading.Lock()

    def read(
        self,
        content: bytes,
        *,
        content_type: str,
    ) -> list[OcrTextObservation]:
        if content_type not in OCR_CONTENT_TYPES:
            raise OcrProcessingError(f"unsupported OCR content type: {content_type}")
        suffix = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }[content_type]

        with TemporaryDirectory(prefix="proofshield-ocr-") as directory:
            source_path = Path(directory) / f"source{suffix}"
            source_path.write_bytes(content)
            try:
                with self._lock:
                    pipeline = self._get_pipeline()
                    results = self._predict(pipeline, source_path)
                    return self._observations(results)
            except OcrProviderError:
                raise
            except Exception as error:
                raise OcrProcessingError(
                    "the local OCR provider could not process this source"
                ) from error

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        if self._pipeline_factory is not None:
            self._pipeline = self._pipeline_factory()
            return self._pipeline
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise OcrProviderUnavailable(
                "PaddleOCR is not installed. Install the local OCR dependencies "
                "with: python -m pip install -e '.[ocr]'"
            ) from error
        try:
            self._pipeline = PaddleOCR(
                ocr_version="PP-OCRv6",
                lang="en",
                use_doc_orientation_classify=True,
                use_doc_unwarping=True,
                use_textline_orientation=True,
            )
        except Exception as error:
            raise OcrProviderUnavailable(
                "PaddleOCR could not initialize its local PP-OCRv6 pipeline"
            ) from error
        return self._pipeline

    @staticmethod
    def _predict(pipeline: Any, source_path: Path) -> Iterable[Any]:
        predict_iter = getattr(pipeline, "predict_iter", None)
        if callable(predict_iter):
            return predict_iter(str(source_path))
        predict = getattr(pipeline, "predict", None)
        if not callable(predict):
            raise OcrProviderUnavailable("the configured PaddleOCR pipeline has no predict method")
        return predict(str(source_path))

    def _observations(self, results: Iterable[Any]) -> list[OcrTextObservation]:
        observations: list[OcrTextObservation] = []
        pages_seen: set[int] = set()
        for result_index, result in enumerate(results):
            payload = _result_mapping(result)
            body = payload.get("res", payload)
            if not isinstance(body, Mapping):
                raise OcrProcessingError("PaddleOCR returned an invalid result body")
            raw_page = body.get("page_index")
            page = int(raw_page) + 1 if raw_page is not None else result_index + 1
            pages_seen.add(page)
            if len(pages_seen) > self.max_pages:
                raise OcrProcessingError(
                    f"document exceeds the {self.max_pages}-page local OCR limit"
                )
            texts = body.get("rec_texts", [])
            scores = body.get("rec_scores", [])
            boxes = body.get("rec_boxes", [])
            if not all(isinstance(values, (list, tuple)) for values in (texts, scores, boxes)):
                raise OcrProcessingError("PaddleOCR returned invalid text observations")
            if not (len(texts) == len(scores) == len(boxes)):
                raise OcrProcessingError("PaddleOCR returned misaligned text observations")
            for text, score, box in zip(texts, scores, boxes, strict=True):
                normalized_text = str(text).strip()
                if not normalized_text:
                    continue
                try:
                    coordinates = tuple(int(round(float(value))) for value in box)
                    observation = OcrTextObservation(
                        page=page,
                        text=normalized_text,
                        confidence=float(score),
                        bounding_box=coordinates,
                    )
                except (TypeError, ValueError) as error:
                    raise OcrProcessingError(
                        "PaddleOCR returned an invalid confidence score or bounding box"
                    ) from error
                observations.append(observation)
        return observations


def _result_mapping(result: Any) -> Mapping[str, Any]:
    payload = getattr(result, "json", result)
    if callable(payload):
        payload = payload()
    if isinstance(payload, Mapping):
        return payload
    raise OcrProcessingError("PaddleOCR returned a result that is not JSON-compatible")
