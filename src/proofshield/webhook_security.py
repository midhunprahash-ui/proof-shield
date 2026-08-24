"""Security helpers for verifying Razorpay webhook requests."""

from __future__ import annotations

import hashlib
import hmac
import re

SIGNATURE_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class InvalidWebhookSignature(ValueError):
    """Raised when a webhook signature is missing, malformed, or incorrect."""


def calculate_webhook_signature(raw_body: bytes, secret: str) -> str:
    """Calculate Razorpay's HMAC-SHA256 hex signature over untouched bytes."""

    if not secret:
        raise ValueError("webhook secret must not be empty")
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify_webhook_signature(
    raw_body: bytes, received_signature: str | None, secret: str
) -> None:
    """Reject a request unless its signature matches in constant time."""

    if received_signature is None:
        raise InvalidWebhookSignature("missing X-Razorpay-Signature header")

    normalized_signature = received_signature.strip()
    if not SIGNATURE_PATTERN.fullmatch(normalized_signature):
        raise InvalidWebhookSignature("malformed X-Razorpay-Signature header")

    expected_signature = calculate_webhook_signature(raw_body, secret)
    if not hmac.compare_digest(expected_signature, normalized_signature.lower()):
        raise InvalidWebhookSignature("webhook signature does not match the raw body")


def body_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()
