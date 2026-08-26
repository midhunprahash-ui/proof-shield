"""FastAPI entrypoint for ProofShield's assessment and webhook API."""

from __future__ import annotations

import json
import logging
import os
from enum import StrEnum
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

from proofshield import __version__
from proofshield.audit import AuditStatus, ClaimResult, EventLedger
from proofshield.case_store import (
    CaseConflictError,
    CaseHistoryEntry,
    CaseNotFoundError,
    CaseRepository,
    CaseSummary,
    DraftConflictError,
    DraftNotFoundError,
    EvidenceConflictError,
    EvidenceFileMetadata,
    ReviewConflictError,
    ReviewNotFoundError,
    new_file_id,
)
from proofshield.domain import Assessment, DisputeCase, EvidenceDocument
from proofshield.drafting import (
    DraftGenerationError,
    EvidenceGroundedDraftGenerator,
    ResponseDraft,
)
from proofshield.evidence import EvidenceSubmission
from proofshield.extraction import (
    DeterministicEvidenceExtractor,
    EvidenceExtractionError,
    EvidenceExtractionProposal,
    EvidenceExtractionRequest,
    EvidenceExtractor,
    UnsupportedExtractionSource,
)
from proofshield.file_store import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileError,
    EvidenceFileStore,
    EvidenceFileTooLarge,
    EvidenceFileUnavailable,
    UnsupportedEvidenceFile,
    safe_original_name,
)
from proofshield.operator_auth import (
    InvalidOperatorToken,
    OperatorAuthenticationUnavailable,
    OperatorAuthenticator,
    OperatorIdentity,
    OperatorNotAuthorized,
    PublicAuthConfig,
)
from proofshield.packet import EvidencePacketError, build_evidence_packet
from proofshield.reviewing import (
    DraftReview,
    DraftReviewRequest,
    create_draft_review,
)
from proofshield.supabase_runtime import (
    SupabaseConfigurationError,
    build_supabase_components,
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
logger = logging.getLogger(__name__)


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
    operator_authenticator: OperatorAuthenticator | None = None,
    public_auth_config: PublicAuthConfig | None = None,
    case_repository: CaseRepository | None = None,
    evidence_file_store: EvidenceFileStore | None = None,
    webhook_ledger: EventLedger | None = None,
    evidence_extractor: EvidenceExtractor | None = None,
) -> FastAPI:
    application = FastAPI(
        title="ProofShield API",
        version=__version__,
        description=(
            "Human-approved evidence assessment for product-not-received chargebacks."
        ),
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
        ],
        expose_headers=[
            "Content-Disposition",
            "X-ProofShield-Packet-SHA256",
            "X-ProofShield-Manifest-SHA256",
        ],
        max_age=600,
    )
    assessor = CaseAssessor()
    draft_generator = EvidenceGroundedDraftGenerator()
    configured_secret = webhook_secret or os.getenv("RAZORPAY_WEBHOOK_SECRET")
    configured_extractor = evidence_extractor or DeterministicEvidenceExtractor()

    supplied_components = (case_repository, evidence_file_store, webhook_ledger)
    if any(component is not None for component in supplied_components) and not all(
        component is not None for component in supplied_components
    ):
        raise ValueError(
            "case_repository, evidence_file_store, and webhook_ledger must be supplied together"
        )

    configuration_error: str | None = None
    if all(component is not None for component in supplied_components):
        configured_cases = case_repository
        configured_files = evidence_file_store
        configured_ledger = webhook_ledger
        configured_authenticator = operator_authenticator
        configured_public_auth = public_auth_config
    else:
        try:
            components = build_supabase_components()
        except SupabaseConfigurationError as error:
            configured_cases = None
            configured_files = None
            configured_ledger = None
            configured_authenticator = None
            configured_public_auth = None
            configuration_error = str(error)
        else:
            configured_cases = components.cases
            configured_files = components.files
            configured_ledger = components.ledger
            configured_authenticator = components.authenticator
            configured_public_auth = components.public_auth_config

    application.state.persistence = "supabase" if configuration_error is None else "unconfigured"
    application.state.configuration_error = configuration_error
    application.state.webhook_ledger = configured_ledger
    application.state.case_repository = configured_cases
    application.state.evidence_file_store = configured_files
    application.state.operator_authenticator = configured_authenticator

    def cases() -> CaseRepository:
        if configured_cases is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase persistence is not configured.",
            )
        return configured_cases

    def files() -> EvidenceFileStore:
        if configured_files is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase Storage is not configured.",
            )
        return configured_files

    def event_ledger() -> EventLedger:
        if configured_ledger is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase webhook persistence is not configured.",
            )
        return configured_ledger

    def require_operator(
        authorization: Annotated[str | None, Header()] = None,
    ) -> OperatorIdentity:
        if configured_authenticator is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase operator authentication is not configured.",
            )
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A Supabase operator bearer token is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return configured_authenticator.authenticate(token.strip())
        except InvalidOperatorToken as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        except OperatorNotAuthorized as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(error),
            ) from error
        except OperatorAuthenticationUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    def require_owned_case(dispute_id: str, operator: OperatorIdentity) -> None:
        try:
            cases().require_case_owner(dispute_id, str(operator.user_id))
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    operator_dependency = Depends(require_operator)

    @application.get("/v1/auth/config", response_model=PublicAuthConfig)
    def get_public_auth_config() -> PublicAuthConfig:
        if configured_public_auth is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Supabase public Auth configuration is not available.",
            )
        return configured_public_auth

    @application.get("/v1/auth/me", response_model=OperatorIdentity)
    def get_operator_identity(
        operator: OperatorIdentity = operator_dependency,
    ) -> OperatorIdentity:
        return operator

    @application.get("/health")
    def health(response: Response) -> dict[str, str]:
        if configuration_error is not None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {
                "status": "configuration_required",
                "version": __version__,
                "persistence": "supabase",
            }
        return {"status": "ok", "version": __version__, "persistence": "supabase"}

    @application.get("/ready")
    def readiness(response: Response) -> dict[str, str]:
        try:
            cases().list_cases()
        except Exception:
            logger.warning("Supabase readiness check failed", exc_info=True)
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "persistence": "supabase"}
        return {"status": "ready", "persistence": "supabase"}

    @application.post("/v1/assessments", response_model=Assessment)
    def create_assessment(case: DisputeCase) -> Assessment:
        return assessor.assess(case)

    @application.post(
        "/v1/cases",
        response_model=DisputeCase,
        status_code=status.HTTP_201_CREATED,
    )
    def create_local_case(
        case: DisputeCase,
        operator: OperatorIdentity = operator_dependency,
    ) -> DisputeCase:
        if case.evidence:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Create the case first, then add evidence through its evidence endpoint.",
            )
        try:
            created = cases().save_case(
                case,
                source="manual_api",
                owner_id=str(operator.user_id),
            )
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
        return cases().get_case(case.dispute_id)

    @application.get("/v1/cases", response_model=list[CaseSummary])
    def list_local_cases(
        operator: OperatorIdentity = operator_dependency,
    ) -> list[CaseSummary]:
        return cases().list_cases(owner_id=str(operator.user_id))

    @application.get("/v1/cases/unassigned", response_model=list[CaseSummary])
    def list_unassigned_cases(
        operator: OperatorIdentity = operator_dependency,
    ) -> list[CaseSummary]:
        del operator
        return cases().list_unassigned_cases()

    @application.post("/v1/cases/{dispute_id}/claim", response_model=DisputeCase)
    def claim_unassigned_case(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> DisputeCase:
        try:
            cases().claim_case(dispute_id, str(operator.user_id))
            return cases().get_case(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except CaseConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error

    @application.get("/v1/cases/{dispute_id}", response_model=DisputeCase)
    def get_local_case(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> DisputeCase:
        try:
            require_owned_case(dispute_id, operator)
            return cases().get_case(dispute_id)
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
        operator: OperatorIdentity = operator_dependency,
    ) -> EvidenceFileMetadata:
        try:
            require_owned_case(dispute_id, operator)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

        try:
            content = await file.read(MAX_EVIDENCE_FILE_BYTES + 1)
            file_id = new_file_id()
            blob = files().save(
                content,
                content_type=file.content_type,
                dispute_id=dispute_id,
                file_id=file_id,
            )
            normalized_content_type = (file.content_type or "").split(
                ";", maxsplit=1
            )[0].strip().lower()
            try:
                return cases().register_evidence_file(
                    dispute_id,
                    file_id=file_id,
                    original_name=safe_original_name(file.filename),
                    content_type=normalized_content_type,
                    size_bytes=blob.size_bytes,
                    sha256=blob.sha256,
                    storage_key=blob.storage_key,
                )
            except Exception:
                try:
                    files().delete(blob.storage_key)
                except Exception:
                    logger.exception(
                        "Failed to remove orphaned evidence object %s", blob.storage_key
                    )
                raise
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
    def list_case_files(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> list[EvidenceFileMetadata]:
        try:
            require_owned_case(dispute_id, operator)
            return cases().list_evidence_files(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/files/{file_id}/extract",
        response_model=EvidenceExtractionProposal,
    )
    def extract_case_file(
        dispute_id: str,
        file_id: str,
        request: EvidenceExtractionRequest,
        operator: OperatorIdentity = operator_dependency,
    ) -> EvidenceExtractionProposal:
        try:
            require_owned_case(dispute_id, operator)
            record = cases().get_evidence_file_record(dispute_id, file_id)
            content = files().read(record.storage_key)
            return configured_extractor.extract(
                content,
                content_type=record.metadata.content_type,
                evidence_type=request.evidence_type,
                source_file_id=file_id,
                source_sha256=record.metadata.sha256,
            )
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except UnsupportedExtractionSource as error:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(error),
            ) from error
        except EvidenceExtractionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        except EvidenceFileUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/evidence",
        response_model=EvidenceDocument,
        status_code=status.HTTP_201_CREATED,
    )
    def add_case_evidence(
        dispute_id: str,
        submission: EvidenceSubmission,
        operator: OperatorIdentity = operator_dependency,
    ) -> EvidenceDocument:
        try:
            require_owned_case(dispute_id, operator)
            file_metadata = None
            if submission.source_file_id is not None:
                file_metadata = cases().get_evidence_file(
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
            added = cases().add_evidence(dispute_id, document)
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
    def assess_local_case(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> Assessment:
        try:
            require_owned_case(dispute_id, operator)
            case = cases().get_case(dispute_id)
            assessment = assessor.assess(case)
            cases().record_assessment(assessment)
            return assessment
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/drafts",
        response_model=ResponseDraft,
        status_code=status.HTTP_201_CREATED,
    )
    def create_case_draft(
        dispute_id: str,
        response: Response,
        operator: OperatorIdentity = operator_dependency,
    ) -> ResponseDraft:
        try:
            require_owned_case(dispute_id, operator)
            case = cases().get_case(dispute_id)
            assessment = assessor.assess(case)
            draft = draft_generator.generate(case, assessment)
            created = cases().save_draft(draft)
            stored = cases().get_draft(dispute_id, draft.draft_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except DraftGenerationError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        except DraftConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        if not created:
            response.status_code = status.HTTP_200_OK
        return stored

    @application.get(
        "/v1/cases/{dispute_id}/drafts",
        response_model=list[ResponseDraft],
    )
    def list_case_drafts(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> list[ResponseDraft]:
        try:
            require_owned_case(dispute_id, operator)
            return cases().list_drafts(dispute_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.get(
        "/v1/cases/{dispute_id}/drafts/{draft_id}",
        response_model=ResponseDraft,
    )
    def get_case_draft(
        dispute_id: str,
        draft_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> ResponseDraft:
        try:
            require_owned_case(dispute_id, operator)
            return cases().get_draft(dispute_id, draft_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except DraftNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.post(
        "/v1/cases/{dispute_id}/drafts/{draft_id}/reviews",
        response_model=DraftReview,
        status_code=status.HTTP_201_CREATED,
    )
    def review_case_draft(
        dispute_id: str,
        draft_id: str,
        request: DraftReviewRequest,
        response: Response,
        operator: OperatorIdentity = operator_dependency,
    ) -> DraftReview:
        try:
            require_owned_case(dispute_id, operator)
            cases().get_draft(dispute_id, draft_id)
            review = create_draft_review(
                dispute_id,
                draft_id,
                request,
                reviewer_user_id=str(operator.user_id),
                reviewer_label=operator.display_name,
            )
            created = cases().save_review(review)
            stored = cases().get_review(dispute_id, draft_id)
        except CaseNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except DraftNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except ReviewConflictError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        if not created:
            response.status_code = status.HTTP_200_OK
        return stored

    @application.get(
        "/v1/cases/{dispute_id}/drafts/{draft_id}/review",
        response_model=DraftReview,
    )
    def get_case_draft_review(
        dispute_id: str,
        draft_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> DraftReview:
        try:
            require_owned_case(dispute_id, operator)
            return cases().get_review(dispute_id, draft_id)
        except (CaseNotFoundError, DraftNotFoundError, ReviewNotFoundError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error

    @application.get(
        "/v1/cases/{dispute_id}/drafts/{draft_id}/packet",
        response_class=Response,
    )
    def download_case_evidence_packet(
        dispute_id: str,
        draft_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> Response:
        try:
            require_owned_case(dispute_id, operator)
            case = cases().get_case(dispute_id)
            draft = cases().get_draft(dispute_id, draft_id)
            review = cases().get_review(dispute_id, draft_id)
            source_files = []
            for citation in draft.citations:
                record = cases().get_evidence_file_record(
                    dispute_id, citation.source_file_id
                )
                source_files.append((record, files().read(record.storage_key)))
            packet = build_evidence_packet(case, draft, review, source_files)
        except (CaseNotFoundError, DraftNotFoundError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(error),
            ) from error
        except ReviewNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="the draft must be approved before its packet can be exported",
            ) from error
        except EvidenceFileUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        except EvidencePacketError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(error),
            ) from error
        return Response(
            content=packet.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    'attachment; filename="proofshield-evidence-packet.zip"'
                ),
                "X-ProofShield-Packet-SHA256": packet.sha256,
                "X-ProofShield-Manifest-SHA256": packet.manifest_sha256,
            },
        )

    @application.get(
        "/v1/cases/{dispute_id}/history",
        response_model=list[CaseHistoryEntry],
    )
    def get_case_history(
        dispute_id: str,
        operator: OperatorIdentity = operator_dependency,
    ) -> list[CaseHistoryEntry]:
        try:
            require_owned_case(dispute_id, operator)
            return cases().get_history(dispute_id)
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
            event_ledger().reject_untrusted(
                event_id,
                digest,
                detail="Request exceeded the one-megabyte webhook limit.",
            )
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload is too large.",
            )

        try:
            verify_webhook_signature(raw_body, x_razorpay_signature, configured_secret)
        except InvalidWebhookSignature as error:
            event_ledger().reject_untrusted(event_id, digest, detail=str(error))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature.",
            ) from error

        if not x_razorpay_event_id or not event_id or len(event_id) > 200:
            event_ledger().reject_untrusted(
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
            event_ledger().reject_untrusted(
                event_id,
                digest,
                detail="Signed webhook body was not valid JSON.",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Webhook body is not valid JSON.",
            ) from error

        if not isinstance(event_type, str) or not event_type:
            event_ledger().reject_untrusted(
                event_id,
                digest,
                detail="Signed JSON body did not contain a valid event type.",
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Webhook body does not contain a valid event type.",
            )

        claim = event_ledger().claim(event_id, digest, event_type=event_type)
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
            event_ledger().finish(
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
            event_ledger().finish(
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
            event_ledger().fail(
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
            cases().save_case(case, source=f"razorpay_webhook:{event_id}")
            stored_case = cases().get_case(case.dispute_id)
            assessment = assessor.assess(stored_case)
            cases().record_assessment(assessment)
            event_ledger().finish(
                event_id,
                digest,
                status=AuditStatus.PROCESSED,
                event_type=event_type,
                dispute_id=case.dispute_id,
                decision=assessment.decision,
                detail="Dispute event was adapted, stored, and assessed.",
            )
        except CaseConflictError as error:
            event_ledger().fail(
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
            event_ledger().fail(
                event_id,
                digest,
                event_type=event_type,
                detail="Unexpected webhook processing failure.",
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook processing failed.",
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


def _cors_origins() -> list[str]:
    configured = os.getenv(
        "PROOFSHIELD_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    return [origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()]


app = create_app()
