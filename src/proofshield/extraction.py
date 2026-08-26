"""Provider-independent, human-reviewed evidence extraction proposals."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from proofshield.domain import EvidenceType


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

        allowed = self._allowed[evidence_type]
        claims: list[ExtractedClaim] = []
        seen: set[ExtractionField] = set()
        warnings: list[str] = []
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
                "extractor": self.name,
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
            extractor=self.name,
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
            match = re.fullmatch(r"\s*([A-Za-z][A-Za-z0-9 _-]{0,80})\s*:\s*(.*?)\s*", line)
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
