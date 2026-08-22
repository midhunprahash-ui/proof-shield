"""FastAPI entrypoint for ProofShield's local API and webhook simulator."""

from __future__ import annotations

import json
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, Request, Response, UploadFile, status
from pydantic import BaseModel, ValidationError

from proofshield import __version__
from proofshield.audit import AuditStatus, ClaimResult, LocalEventLedger
from proofshield.case_store import (
    CaseConflictError,
    CaseHistoryEntry,
    CaseNotFoundError,
    CaseSummary,
    EvidenceConflictError,
    EvidenceFileMetadata,
    LocalCaseRepository,
)
from proofshield.domain import Assessment, DisputeCase, EvidenceDocument
from proofshield.evidence import EvidenceSubmission
from proofshield.file_store import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileError,
    EvidenceFileTooLarge,
    LocalEvidenceFileStore,
    UnsupportedEvidenceFile,
    safe_original_name,
)
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
    database_path: Path | None = None,
    evidence_storage_path: Path | None = None,
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
    configured_database_path = database_path or Path(
        os.getenv("PROOFSHIELD_DB_PATH", "data/runtime/proofshield.sqlite3")
    )
    configured_evidence_path = evidence_storage_path or Path(
        os.getenv("PROOFSHIELD_EVIDENCE_PATH", "data/runtime/evidence")
    )
    ledger = LocalEventLedger(configured_ledger_path)
    case_repository = LocalCaseRepository(configured_database_path)
    evidence_file_store = LocalEvidenceFileStore(configured_evidence_path)
    application.state.webhook_ledger = ledger
    application.state.case_repository = case_repository
    application.state.evidence_file_store = evidence_file_store

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @application.post("/v1/assessments", response_model=Assessment)
    def create_assessment(case: DisputeCase) -> Assessment:
        return assessor.assess(case)

    @application.post(
        "/v1/cases",
        response_model=DisputeCase,
        status_code=status.HTTP_201_CREATED,
    )
    def create_local_case(case: DisputeCase) -> DisputeCase:
        if case.evidence:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Create the case first, then add evidence through its evidence endpoint.",
            )
        try:
            created = case_repository.save_case(case, source="manual_api")
        except CaseConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        if not created:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"case {case.dispute_id} already exists",
            )
        return case_repository.get_case(case.dispute_id)

    @application.get("/v1/cases", response_model=list[CaseSummary])
    def list_local_cases() -> list[CaseSummary]:
        return case_repository.list_cases()

    @application.get("/v1/cases/{dispute_id}", response_model=DisputeCase)
    def get_local_case(dispute_id: str) -> DisputeCase:
        try:
            return case_repository.get_case(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/files",
        response_model=EvidenceFileMetadata,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_case_file(
        dispute_id: str,
        file: Annotated[UploadFile, File(description="Local evidence source")],
    ) -> EvidenceFileMetadata:
        try:
            case_repository.get_case(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

        try:
            content = await file.read(MAX_EVIDENCE_FILE_BYTES + 1)
            blob = evidence_file_store.save(content, content_type=file.content_type)
            normalized_content_type = (file.content_type or "").split(
                ";", maxsplit=1
            )[0].strip().lower()
            return case_repository.register_evidence_file(
                dispute_id,
                original_name=safe_original_name(file.filename),
                content_type=normalized_content_type,
                size_bytes=blob.size_bytes,
                sha256=blob.sha256,
                storage_key=blob.storage_key,
            )
        except EvidenceFileTooLarge as error:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=str(error),
            ) from error
        except UnsupportedEvidenceFile as error:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(error),
            ) from error
        except EvidenceFileError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error
        finally:
            await file.close()

    @application.get(
        "/v1/cases/{dispute_id}/files",
        response_model=list[EvidenceFileMetadata],
    )
    def list_case_files(dispute_id: str) -> list[EvidenceFileMetadata]:
        try:
            return case_repository.list_evidence_files(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/evidence",
        response_model=EvidenceDocument,
        status_code=status.HTTP_201_CREATED,
    )
    def add_case_evidence(
        dispute_id: str, submission: EvidenceSubmission
    ) -> EvidenceDocument:
        try:
            file_metadata = None
            if submission.source_file_id is not None:
                file_metadata = case_repository.get_evidence_file(
                    dispute_id, submission.source_file_id
                )
            document = submission.to_document(
                resolved_source_name=(
                    file_metadata.original_name if file_metadata is not None else None
                ),
                resolved_source_sha256=(
                    file_metadata.sha256 if file_metadata is not None else None
                ),
            )
            added = case_repository.add_evidence(dispute_id, document)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except EvidenceConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        if not added:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"evidence {document.evidence_id} is already attached to this case",
            )
        return document

    @application.post(
        "/v1/cases/{dispute_id}/assessment",
        response_model=Assessment,
    )
    def assess_local_case(dispute_id: str) -> Assessment:
        try:
            case = case_repository.get_case(dispute_id)
            assessment = assessor.assess(case)
            case_repository.record_assessment(assessment)
            return assessment
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.get(
        "/v1/cases/{dispute_id}/history",
        response_model=list[CaseHistoryEntry],
    )
    def get_case_history(dispute_id: str) -> list[CaseHistoryEntry]:
        try:
            return case_repository.get_history(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

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
            case_repository.save_case(case, source=f"razorpay_webhook:{event_id}")
            stored_case = case_repository.get_case(case.dispute_id)
            assessment = assessor.assess(stored_case)
            case_repository.record_assessment(assessment)
            ledger.finish(
                event_id,
                digest,
                status=AuditStatus.PROCESSED,
                event_type=event_type,
                dispute_id=case.dispute_id,
                decision=assessment.decision,
                detail="Dispute event was adapted and assessed locally.",
            )
        except CaseConflictError as error:
            ledger.fail(
                event_id,
                digest,
                event_type=event_type,
                detail="Stored dispute conflicts with the signed webhook facts.",
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
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
