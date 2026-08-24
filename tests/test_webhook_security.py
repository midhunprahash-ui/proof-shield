import pytest

from proofshield.webhook_security import (
    InvalidWebhookSignature,
    calculate_webhook_signature,
    verify_webhook_signature,
)


def test_valid_signature_uses_exact_raw_bytes() -> None:
    raw_body = b'{"event":"payment.dispute.created", "spacing":"is-significant"}'
    signature = calculate_webhook_signature(raw_body, "local-secret")

    verify_webhook_signature(raw_body, signature, "local-secret")


def test_reencoded_body_does_not_match_original_signature() -> None:
    original = b'{"event":"payment.dispute.created", "value":1}'
    reencoded = b'{"event":"payment.dispute.created","value":1}'
    signature = calculate_webhook_signature(original, "local-secret")

    with pytest.raises(InvalidWebhookSignature, match="does not match"):
        verify_webhook_signature(reencoded, signature, "local-secret")


@pytest.mark.parametrize("signature", [None, "", "not-hex", "a" * 63])
def test_missing_or_malformed_signatures_are_rejected(signature: str | None) -> None:
    with pytest.raises(InvalidWebhookSignature):
        verify_webhook_signature(b"{}", signature, "local-secret")
