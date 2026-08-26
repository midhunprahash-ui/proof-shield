import hashlib

import pytest

from proofshield.domain import EvidenceType
from proofshield.extraction import (
    DeterministicEvidenceExtractor,
    EvidenceExtractionError,
    ExtractionField,
    RoutingEvidenceExtractor,
    UnsupportedExtractionSource,
    build_configured_evidence_extractor,
)
from proofshield.ocr import OcrTextObservation


class StaticOcrProvider:
    name = "test-local-ocr"

    def __init__(self, observations: list[OcrTextObservation]) -> None:
        self.observations = observations
        self.calls = 0

    def read(self, content: bytes, *, content_type: str) -> list[OcrTextObservation]:
        del content, content_type
        self.calls += 1
        return self.observations


def extract(content: bytes, content_type: str, evidence_type: EvidenceType):
    return DeterministicEvidenceExtractor().extract(
        content,
        content_type=content_type,
        evidence_type=evidence_type,
        source_file_id="file_test",
        source_sha256=hashlib.sha256(content).hexdigest(),
    )


def test_json_invoice_returns_typed_unverified_proposals() -> None:
    proposal = extract(
        b'{"order_id":"order_7","payment_id":"pay_7","amount":"1,249.50"}',
        "application/json",
        EvidenceType.INVOICE,
    )

    assert proposal.human_confirmation_required is True
    assert proposal.proposal_id.startswith("extract_")
    assert proposal.warnings == []
    assert {
        claim.field: (claim.value, claim.source_reference, claim.confidence)
        for claim in proposal.claims
    } == {
        ExtractionField.ORDER_ID: ("order_7", "#/order_id", 0.99),
        ExtractionField.PAYMENT_ID: ("pay_7", "#/payment_id", 0.99),
        ExtractionField.AMOUNT: ("1249.50", "#/amount", 0.99),
    }
    assert "source_verified" not in proposal.model_dump()


def test_text_delivery_keeps_line_references_and_reports_missing_fields() -> None:
    proposal = extract(
        b"Order ID: order_8\nDelivery status: delivered\n",
        "text/plain",
        EvidenceType.DELIVERY_PROOF,
    )

    assert [(claim.field, claim.source_reference) for claim in proposal.claims] == [
        (ExtractionField.ORDER_ID, "line 1"),
        (ExtractionField.DELIVERY_STATUS, "line 2"),
    ]
    assert proposal.warnings == ["missing required proposed fields: payment_id"]


def test_customer_boolean_is_normalized_but_never_verified() -> None:
    proposal = extract(
        b"Message: Package received\nAcknowledged delivery: yes\n",
        "text/plain",
        EvidenceType.CUSTOMER_COMMUNICATION,
    )

    acknowledged = next(
        claim
        for claim in proposal.claims
        if claim.field == ExtractionField.CUSTOMER_ACKNOWLEDGED_DELIVERY
    )
    assert acknowledged.value is True
    assert proposal.human_confirmation_required is True


def test_pdf_requires_a_configured_provider() -> None:
    content = b"%PDF-1.4 synthetic"
    with pytest.raises(UnsupportedExtractionSource, match="configured provider"):
        extract(content, "application/pdf", EvidenceType.INVOICE)


def test_registered_hash_must_match_source_bytes() -> None:
    with pytest.raises(EvidenceExtractionError, match="SHA-256"):
        DeterministicEvidenceExtractor().extract(
            b"Order ID: order_9",
            content_type="text/plain",
            evidence_type=EvidenceType.INVOICE,
            source_file_id="file_test",
            source_sha256="0" * 64,
        )


def test_ocr_image_returns_located_unverified_invoice_proposals() -> None:
    provider = StaticOcrProvider(
        [
            OcrTextObservation(
                page=1,
                text="Order ID:",
                confidence=0.97,
                bounding_box=(10, 20, 100, 45),
            ),
            OcrTextObservation(
                page=1,
                text="order_ocr_12",
                confidence=0.96,
                bounding_box=(120, 20, 260, 45),
            ),
            OcrTextObservation(
                page=1,
                text="Payment ID: pay_ocr_12",
                confidence=0.95,
                bounding_box=(10, 70, 280, 95),
            ),
            OcrTextObservation(
                page=1,
                text="Invoice amount: INR 1,249.50",
                confidence=0.93,
                bounding_box=(10, 120, 300, 145),
            ),
        ]
    )
    extractor = RoutingEvidenceExtractor(provider)
    content = b"\x89PNG\r\n\x1a\nsynthetic"

    proposal = extractor.extract(
        content,
        content_type="image/png",
        evidence_type=EvidenceType.INVOICE,
        source_file_id="file_ocr",
        source_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert proposal.extractor == "test-local-ocr+labelled-fields-v1"
    assert proposal.human_confirmation_required is True
    assert {
        claim.field: (claim.value, claim.source_reference)
        for claim in proposal.claims
    } == {
        ExtractionField.ORDER_ID: (
            "order_ocr_12",
            "page 1, box [10,20,260,45]",
        ),
        ExtractionField.PAYMENT_ID: (
            "pay_ocr_12",
            "page 1, box [10,70,280,95]",
        ),
        ExtractionField.AMOUNT: (
            "1249.50",
            "page 1, box [10,120,300,145]",
        ),
    }
    assert "source_verified" not in proposal.model_dump()


def test_ocr_hash_is_checked_before_the_provider_receives_bytes() -> None:
    provider = StaticOcrProvider([])
    extractor = RoutingEvidenceExtractor(provider)

    with pytest.raises(EvidenceExtractionError, match="SHA-256"):
        extractor.extract(
            b"synthetic",
            content_type="image/jpeg",
            evidence_type=EvidenceType.INVOICE,
            source_file_id="file_ocr",
            source_sha256="0" * 64,
        )

    assert provider.calls == 0


def test_low_confidence_ocr_text_is_not_proposed() -> None:
    provider = StaticOcrProvider(
        [
            OcrTextObservation(
                page=1,
                text="Order ID: guessed-order",
                confidence=0.2,
                bounding_box=(1, 1, 100, 20),
            )
        ]
    )
    extractor = RoutingEvidenceExtractor(provider, minimum_ocr_confidence=0.5)
    content = b"synthetic"

    proposal = extractor.extract(
        content,
        content_type="image/jpeg",
        evidence_type=EvidenceType.INVOICE,
        source_file_id="file_ocr",
        source_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert proposal.claims == []
    assert any("confidence floor" in warning for warning in proposal.warnings)


def test_configured_extractor_can_disable_ocr_without_disabling_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROOFSHIELD_OCR_PROVIDER", "disabled")
    extractor = build_configured_evidence_extractor()
    content = b"Order ID: order_text_12"

    proposal = extractor.extract(
        content,
        content_type="text/plain",
        evidence_type=EvidenceType.INVOICE,
        source_file_id="file_text",
        source_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert proposal.claims[0].value == "order_text_12"
    with pytest.raises(UnsupportedExtractionSource, match="disabled"):
        extractor.extract(
            b"synthetic image",
            content_type="image/png",
            evidence_type=EvidenceType.INVOICE,
            source_file_id="file_image",
            source_sha256=hashlib.sha256(b"synthetic image").hexdigest(),
        )


def test_unknown_ocr_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROOFSHIELD_OCR_PROVIDER", "unknown-cloud")

    with pytest.raises(ValueError, match="must be 'paddle' or 'disabled'"):
        build_configured_evidence_extractor()
