import hashlib

import pytest

from proofshield.domain import EvidenceType
from proofshield.extraction import (
    DeterministicEvidenceExtractor,
    EvidenceExtractionError,
    ExtractionField,
    UnsupportedExtractionSource,
)


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
