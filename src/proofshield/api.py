"""FastAPI entrypoint for ProofShield's local API and webhook simulator."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ValidationError

from proofshield import __version__
from proofshield.audit import AuditStatus, ClaimResult, LocalEventLedger
from proofshield.domain import Assessment, DisputeCase
from proofshield.verifier import CaseAssessor
from proofshield.webhook_adapter import WebhookAdaptationError, adapt_dispute_created_event
from proofshield.webhook_models import RazorpayDisputeWebhook
from proofshield.webhook_security import (
    InvalidWebhookSignature,
    body_sha256,
    verify_webhook_signature,
)

MAX_WEBHOOK_BYTES = 1_000_000


class WebhookReceiptStatus(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    NEEDS_ENRICHMENT = "NEEDS_ENRICHMENT"


class WebhookReceipt(BaseModel):
    event_id: str
    status: WebhookReceiptStatus
    dispute_id: str | None = None
    decision: str | None = None
    detail: str


def create_app(
    *,
    webhook_secret: str | None = None,
    ledger_path: Path | None = None,
) -> FastAPI:
    application = FastAPI(
        title="ProofShield API",
        version=__version__,
        description=(
            "Human-approved evidence assessment for product-not-received chargebacks."
        ),
    )
    assessor = CaseAssessor()
    configured_secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET")
    configured_ledger_path = ledger_path or Path(
        os.getenv("PROOFSHIELD_AUDIT_PATH", "data/runtime/webhook_audit.jsonl")
    )
    ledger = LocalEventLedger(configured_ledger_path)
    application.state.webhook_ledger = ledger

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.post("/v1/assessments", response_model=Assessment)
    def create_assessment(case: DisputeCase) -> Assessment:
        return assessor.assess(case)

    @application.post(
        "/v1/webhooks/razorpay",
        response_model=WebhookReceipt,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def receive_razorpay_webhook(
        request: Request,
        response: Response,
        x_razorpay_signature: Annotated[str | None, Header()] = None,
        x_razorpay_event_id: Annotated[str | None, Header()] = None,
    ) -> WebhookReceipt:
        raw_body = await request.body()
        digest = body_sha256(raw_body)
        event_id = (x_razorpay_event_id or "UNAVAILABLE").strip()

        if configured_secret is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RAZORPAY_WEBHOOK_SECRET is not configured.",
            )
        if len(raw_body) > MAX_WEBHOOK_BYTES:
            ledger.reject_untrusted(
                event_id,
                digest,
                detail="Request exceeded the one-megabyte local webhook limit.",
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload is too large.",
            )

        try:
            verify_webhook_signature(raw_body, x_razorpay_signature, configured_secret)
        except InvalidWebhookSignature as error:
            ledger.reject_untrusted(event_id, digest, detail=str(error))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature.",
            ) from error

        if not x_razorpay_event_id or not event_id or len(event_id) > 200:
            ledger.reject_untrusted(
                event_id,
                digest,
                detail="Signed request did not include a valid x-razorpay-event-id.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A valid x-razorpay-event-id header is required.",
            )

        try:
            untyped_payload = json.loads(raw_body)
            event_type = (
                untyped_payload.get("event") if isinstance(untyped_payload, dict) else None
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            ledger.reject_untrusted(
                event_id,
                digest,
                detail="Signed webhook body was not valid JSON.",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Webhook body is not valid JSON.",
            ) from error

        if not isinstance(event_type, str) or not event_type:
            ledger.reject_untrusted(
                event_id,
                digest,
                detail="Signed JSON body did not contain a valid event type.",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Webhook body does not contain a valid event type.",
            )

        claim = ledger.claim(event_id, digest, event_type=event_type)
        if claim == ClaimResult.DUPLICATE:
            response.status_code = status.HTTP_200_OK
            return WebhookReceipt(
                event_id=event_id,
                status=WebhookReceiptStatus.DUPLICATE,
                detail="Event was already processed; no work was repeated.",
            )
        if claim == ClaimResult.CONFLICT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Event ID was previously used with a different signed body.",
            )

        if event_type != "payment.dispute.created":
            ledger.finish(
                event_id,
                digest,
                status=AuditStatus.IGNORED,
                event_type=event_type,
                detail="Verified event is outside the current product-not-received workflow.",
            )
            return WebhookReceipt(
                event_id=event_id,
                status=WebhookReceiptStatus.IGNORED,
                detail="Verified event is outside the current workflow.",
            )

        try:
            webhook = RazorpayDisputeWebhook.model_validate(untyped_payload)
            case = adapt_dispute_created_event(webhook)
        except WebhookAdaptationError as error:
            ledger.finish(
                event_id,
                digest,
                status=AuditStatus.NEEDS_ENRICHMENT,
                event_type=event_type,
                detail=str(error),
            )
            return WebhookReceipt(
                event_id=event_id,
                status=WebhookReceiptStatus.NEEDS_ENRICHMENT,
                detail=str(error),
            )
        except ValidationError as error:
            ledger.fail(
                event_id,
                digest,
                event_type=event_type,
                detail="Signed payload did not match the expected dispute-created contract.",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Signed payload does not match the expected contract.",
            ) from error

        try:
            assessment = assessor.assess(case)
            ledger.finish(
                event_id,
                digest,
                status=AuditStatus.PROCESSED,
                event_type=event_type,
                dispute_id=case.dispute_id,
                decision=assessment.decision,
                detail="Dispute event was adapted and assessed locally.",
            )
        except Exception as error:
            ledger.fail(
                event_id,
                digest,
                event_type=event_type,
                detail="Unexpected local processing failure.",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Local webhook processing failed.",
            ) from error
        return WebhookReceipt(
            event_id=event_id,
            status=WebhookReceiptStatus.PROCESSED,
            dispute_id=case.dispute_id,
            decision=assessment.decision,
            detail=(
                "Webhook was verified and assessed. Evidence enrichment is still required "
                "before a response can be drafted."
            ),
        )

    return application


app = create_app()
