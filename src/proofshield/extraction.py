"""Provider-independent, human-reviewed evidence extraction proposals."""

from __future__ import annotations

import hashlib
import json
import os
import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from proofshield.domain import EvidenceType
from proofshield.ocr import (
    OCR_CONTENT_TYPES,
    DocumentOcrProvider,
    OcrProcessingError,
    OcrProviderUnavailable,
    OcrTextObservation,
    PaddleOcrProvider,
)


class EvidenceExtractionError(RuntimeError):
    """Base class for evidence extraction failures."""


class UnsupportedExtractionSource(EvidenceExtractionError):
    pass


class ExtractionField(StrEnum):
    ORDER_ID = "order_id"
    PAYMENT_ID = "payment_id"
    AMOUNT = "amount"
    ISSUED_AT = "issued_at"
    DELIVERY_STATUS = "delivery_status"
    CUSTOMER_ACKNOWLEDGED_DELIVERY = "customer_acknowledged_delivery"
    TEXT = "text"


class ExtractedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: ExtractionField
    value: str | bool
    confidence: float = Field(ge=0, le=1)
    source_reference: str = Field(min_length=1, max_length=500)


class EvidenceExtractionProposal(BaseModel):
    """Unverified facts that must be checked by a human before use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(pattern=r"^extract_[0-9a-f]{64}$")
    source_file_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_type: EvidenceType
    extractor: str = Field(min_length=1, max_length=200)
    claims: list[ExtractedClaim]
    warnings: list[str]
    human_confirmation_required: bool = True


class EvidenceExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: EvidenceType


class EvidenceExtractor(Protocol):
    def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        evidence_type: EvidenceType,
        source_file_id: str,
        source_sha256: str,
    ) -> EvidenceExtractionProposal: ...


class DeterministicEvidenceExtractor:
    """Extract exact labelled fields from JSON or UTF-8 text without a model."""

    name = "deterministic-labelled-fields-v1"

    _aliases = {
        "order": ExtractionField.ORDER_ID,
        "order_id": ExtractionField.ORDER_ID,
        "payment": ExtractionField.PAYMENT_ID,
        "payment_id": ExtractionField.PAYMENT_ID,
        "amount": ExtractionField.AMOUNT,
        "invoice_amount": ExtractionField.AMOUNT,
        "issued_at": ExtractionField.ISSUED_AT,
        "invoice_date": ExtractionField.ISSUED_AT,
        "status": ExtractionField.DELIVERY_STATUS,
        "delivery_status": ExtractionField.DELIVERY_STATUS,
        "customer_acknowledged_delivery": (
            ExtractionField.CUSTOMER_ACKNOWLEDGED_DELIVERY
        ),
        "acknowledged_delivery": ExtractionField.CUSTOMER_ACKNOWLEDGED_DELIVERY,
        "text": ExtractionField.TEXT,
        "message": ExtractionField.TEXT,
    }

    _allowed = {
        EvidenceType.INVOICE: {
            ExtractionField.ORDER_ID,
            ExtractionField.PAYMENT_ID,
            ExtractionField.AMOUNT,
            ExtractionField.ISSUED_AT,
        },
        EvidenceType.DELIVERY_PROOF: {
            ExtractionField.ORDER_ID,
            ExtractionField.PAYMENT_ID,
            ExtractionField.DELIVERY_STATUS,
        },
        EvidenceType.CUSTOMER_COMMUNICATION: {
            ExtractionField.ORDER_ID,
            ExtractionField.PAYMENT_ID,
            ExtractionField.CUSTOMER_ACKNOWLEDGED_DELIVERY,
            ExtractionField.TEXT,
        },
    }

    _required = {
        EvidenceType.INVOICE: {
            ExtractionField.ORDER_ID,
            ExtractionField.PAYMENT_ID,
            ExtractionField.AMOUNT,
        },
        EvidenceType.DELIVERY_PROOF: {
            ExtractionField.ORDER_ID,
            ExtractionField.PAYMENT_ID,
            ExtractionField.DELIVERY_STATUS,
        },
        EvidenceType.CUSTOMER_COMMUNICATION: {ExtractionField.TEXT},
    }

    _label_pattern = re.compile(
        r"\s*([A-Za-z][A-Za-z0-9 _-]{0,80})\s*:\s*(.*?)\s*"
    )

    def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        evidence_type: EvidenceType,
        source_file_id: str,
        source_sha256: str,
    ) -> EvidenceExtractionProposal:
        if hashlib.sha256(content).hexdigest() != source_sha256:
            raise EvidenceExtractionError(
                "source bytes do not match the registered SHA-256"
            )
        if content_type == "application/json":
            raw_claims = self._from_json(content)
        elif content_type == "text/plain":
            raw_claims = self._from_text(content)
        else:
            raise UnsupportedExtractionSource(
                "the local extractor supports JSON and UTF-8 text; "
                "PDF and image extraction require a configured provider"
            )

        return self.proposal_from_raw_claims(
            raw_claims,
            evidence_type=evidence_type,
            source_file_id=source_file_id,
            source_sha256=source_sha256,
            extractor_name=self.name,
        )

    def proposal_from_raw_claims(
        self,
        raw_claims: list[tuple[str, Any, str, float]],
        *,
        evidence_type: EvidenceType,
        source_file_id: str,
        source_sha256: str,
        extractor_name: str,
        initial_warnings: list[str] | None = None,
    ) -> EvidenceExtractionProposal:
        """Normalize provider observations through the same evidence contract."""

        allowed = self._allowed[evidence_type]
        claims: list[ExtractedClaim] = []
        seen: set[ExtractionField] = set()
        warnings = list(initial_warnings or [])
        for key, value, reference, confidence in raw_claims:
            field = self._aliases.get(self._normalize_key(key))
            if field is None or field not in allowed or field in seen:
                continue
            normalized_value = self._normalize_value(field, value)
            if normalized_value is None:
                warnings.append(f"{field.value} was present but could not be normalized")
                continue
            claims.append(
                ExtractedClaim(
                    field=field,
                    value=normalized_value,
                    confidence=confidence,
                    source_reference=reference,
                )
            )
            seen.add(field)

        missing = sorted(field.value for field in self._required[evidence_type] - seen)
        if missing:
            warnings.append("missing required proposed fields: " + ", ".join(missing))
        if not claims:
            warnings.append("no supported labelled fields were found")

        canonical = json.dumps(
            {
                "extractor": extractor_name,
                "source_sha256": source_sha256,
                "evidence_type": evidence_type,
                "claims": [claim.model_dump(mode="json") for claim in claims],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        proposal_id = "extract_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return EvidenceExtractionProposal(
            proposal_id=proposal_id,
            source_file_id=source_file_id,
            source_sha256=source_sha256,
            evidence_type=evidence_type,
            extractor=extractor_name,
            claims=claims,
            warnings=warnings,
        )

    @staticmethod
    def _from_json(content: bytes) -> list[tuple[str, Any, str, float]]:
        try:
            payload = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise EvidenceExtractionError("source JSON could not be decoded") from error
        if not isinstance(payload, dict):
            raise EvidenceExtractionError("source JSON must be an object")
        return [
            (str(key), value, f"#/{key}", 0.99)
            for key, value in payload.items()
            if not isinstance(value, (dict, list))
        ]

    @staticmethod
    def _from_text(content: bytes) -> list[tuple[str, Any, str, float]]:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise EvidenceExtractionError("source text could not be decoded") from error
        rows = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = DeterministicEvidenceExtractor._label_pattern.fullmatch(line)
            if match and match.group(2):
                rows.append((match.group(1), match.group(2), f"line {line_number}", 0.95))
        return rows

    @staticmethod
    def _normalize_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")

    @staticmethod
    def _normalize_value(field: ExtractionField, value: Any) -> str | bool | None:
        if field == ExtractionField.CUSTOMER_ACKNOWLEDGED_DELIVERY:
            if isinstance(value, bool):
                return value
            normalized = str(value).strip().casefold()
            if normalized in {"true", "yes"}:
                return True
            if normalized in {"false", "no"}:
                return False
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if field == ExtractionField.AMOUNT:
            amount = re.sub(r"[^0-9.-]", "", normalized.replace(",", ""))
            if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", amount):
                return None
            return amount
        return normalized[:10_000]


class OcrEvidenceExtractor:
    """Turn located OCR text into unverified, normalized field proposals."""

    def __init__(
        self,
        provider: DocumentOcrProvider,
        *,
        minimum_confidence: float = 0.5,
    ) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between zero and one")
        self.provider = provider
        self.minimum_confidence = minimum_confidence
        self._labelled = DeterministicEvidenceExtractor()

    @property
    def name(self) -> str:
        return f"{self.provider.name}+labelled-fields-v1"

    def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        evidence_type: EvidenceType,
        source_file_id: str,
        source_sha256: str,
    ) -> EvidenceExtractionProposal:
        if hashlib.sha256(content).hexdigest() != source_sha256:
            raise EvidenceExtractionError(
                "source bytes do not match the registered SHA-256"
            )
        if content_type not in OCR_CONTENT_TYPES:
            raise UnsupportedExtractionSource(
                f"the configured OCR provider does not support {content_type}"
            )
        try:
            observations = self.provider.read(content, content_type=content_type)
        except OcrProviderUnavailable:
            raise
        except OcrProcessingError as error:
            raise EvidenceExtractionError(str(error)) from error

        accepted = [
            observation
            for observation in observations
            if observation.confidence >= self.minimum_confidence
        ]
        warnings: list[str] = []
        rejected_count = len(observations) - len(accepted)
        if rejected_count:
            warnings.append(
                f"ignored {rejected_count} OCR observations below the confidence floor"
            )
        if not accepted:
            warnings.append("OCR returned no readable text above the confidence floor")

        raw_claims = self._raw_claims(accepted)
        low_confidence_fields: set[str] = set()
        for key, _value, _reference, confidence in raw_claims:
            field = self._labelled._aliases.get(self._labelled._normalize_key(key))
            if field is not None and confidence < 0.85:
                low_confidence_fields.add(field.value)
        if low_confidence_fields:
            warnings.append(
                "low OCR confidence requires extra review: "
                + ", ".join(sorted(low_confidence_fields))
            )
        return self._labelled.proposal_from_raw_claims(
            raw_claims,
            evidence_type=evidence_type,
            source_file_id=source_file_id,
            source_sha256=source_sha256,
            extractor_name=self.name,
            initial_warnings=warnings,
        )

    def _raw_claims(
        self,
        observations: list[OcrTextObservation],
    ) -> list[tuple[str, Any, str, float]]:
        raw_claims: list[tuple[str, Any, str, float]] = []
        for observation in observations:
            match = self._labelled._label_pattern.fullmatch(observation.text)
            if match and match.group(2):
                raw_claims.append(
                    (
                        match.group(1),
                        match.group(2),
                        observation.source_reference,
                        observation.confidence,
                    )
                )

        for row in _group_ocr_rows(observations):
            for index, label_observation in enumerate(row[:-1]):
                normalized_label = self._labelled._normalize_key(
                    label_observation.text.rstrip(":")
                )
                if normalized_label not in self._labelled._aliases:
                    continue
                value_observation = row[index + 1]
                direct_match = self._labelled._label_pattern.fullmatch(
                    label_observation.text
                )
                if direct_match and direct_match.group(2):
                    continue
                raw_claims.append(
                    (
                        label_observation.text.rstrip(":"),
                        value_observation.text,
                        _combined_reference(label_observation, value_observation),
                        min(
                            label_observation.confidence,
                            value_observation.confidence,
                        ),
                    )
                )
        raw_claims.sort(key=lambda claim: claim[3], reverse=True)
        return raw_claims


class RoutingEvidenceExtractor:
    """Stable boundary that can swap local OCR for a future cloud provider."""

    name = "proofshield-extraction-router-v1"

    def __init__(
        self,
        ocr_provider: DocumentOcrProvider | None,
        *,
        minimum_ocr_confidence: float = 0.5,
    ) -> None:
        self.structured = DeterministicEvidenceExtractor()
        self.ocr = (
            OcrEvidenceExtractor(
                ocr_provider,
                minimum_confidence=minimum_ocr_confidence,
            )
            if ocr_provider is not None
            else None
        )

    def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        evidence_type: EvidenceType,
        source_file_id: str,
        source_sha256: str,
    ) -> EvidenceExtractionProposal:
        if content_type in {"application/json", "text/plain"}:
            return self.structured.extract(
                content,
                content_type=content_type,
                evidence_type=evidence_type,
                source_file_id=source_file_id,
                source_sha256=source_sha256,
            )
        if content_type in OCR_CONTENT_TYPES:
            if self.ocr is None:
                raise UnsupportedExtractionSource(
                    "PDF and image extraction is disabled by configuration"
                )
            return self.ocr.extract(
                content,
                content_type=content_type,
                evidence_type=evidence_type,
                source_file_id=source_file_id,
                source_sha256=source_sha256,
            )
        raise UnsupportedExtractionSource(
            f"no extraction route supports {content_type}"
        )


def build_configured_evidence_extractor() -> EvidenceExtractor:
    """Select a provider without changing the extraction API or trust boundary."""

    provider_name = os.getenv("PROOFSHIELD_OCR_PROVIDER", "paddle").strip().casefold()
    minimum_confidence = _environment_float(
        "PROOFSHIELD_OCR_MIN_CONFIDENCE",
        default=0.5,
        minimum=0,
        maximum=1,
    )
    if provider_name in {"", "disabled", "none"}:
        return RoutingEvidenceExtractor(
            None,
            minimum_ocr_confidence=minimum_confidence,
        )
    if provider_name == "paddle":
        max_pages = _environment_int(
            "PROOFSHIELD_OCR_MAX_PAGES",
            default=10,
            minimum=1,
            maximum=50,
        )
        return RoutingEvidenceExtractor(
            PaddleOcrProvider(max_pages=max_pages),
            minimum_ocr_confidence=minimum_confidence,
        )
    raise ValueError(
        "PROOFSHIELD_OCR_PROVIDER must be 'paddle' or 'disabled'; "
        "future cloud providers plug into the same DocumentOcrProvider contract"
    )


def _group_ocr_rows(
    observations: list[OcrTextObservation],
) -> list[list[OcrTextObservation]]:
    rows: list[list[OcrTextObservation]] = []
    for observation in sorted(
        observations,
        key=lambda item: (item.page, item.bounding_box[1], item.bounding_box[0]),
    ):
        if rows and _same_visual_row(rows[-1][0], observation):
            rows[-1].append(observation)
            rows[-1].sort(key=lambda item: item.bounding_box[0])
        else:
            rows.append([observation])
    return rows


def _same_visual_row(first: OcrTextObservation, second: OcrTextObservation) -> bool:
    if first.page != second.page:
        return False
    _left_a, top_a, _right_a, bottom_a = first.bounding_box
    _left_b, top_b, _right_b, bottom_b = second.bounding_box
    overlap = min(bottom_a, bottom_b) - max(top_a, top_b)
    minimum_height = min(bottom_a - top_a, bottom_b - top_b)
    return overlap > 0 and overlap / minimum_height >= 0.5


def _combined_reference(
    first: OcrTextObservation,
    second: OcrTextObservation,
) -> str:
    left = min(first.bounding_box[0], second.bounding_box[0])
    top = min(first.bounding_box[1], second.bounding_box[1])
    right = max(first.bounding_box[2], second.bounding_box[2])
    bottom = max(first.bounding_box[3], second.bounding_box[3])
    return f"page {first.page}, box [{left},{top},{right},{bottom}]"


def _environment_float(
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a number") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _environment_int(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
