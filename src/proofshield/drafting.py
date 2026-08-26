"""Deterministic, evidence-grounded chargeback response drafting."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from proofshield.consistency import (
    ConsistencyStatus,
    EvidenceConsistencyAnalyzer,
    EvidenceConsistencyReport,
)
from proofshield.domain import (
    Assessment,
    Decision,
    DisputeCase,
    EvidenceDocument,
    EvidenceType,
)

DRAFT_GENERATOR = "proofshield-template-v1"


class DraftStatus(StrEnum):
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"


class DraftCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=r"^E[1-9][0-9]*$")
    evidence_id: str = Field(min_length=1, max_length=200)
    evidence_type: EvidenceType
    source_file_id: str = Field(min_length=1, max_length=200)
    source_name: str = Field(min_length=1, max_length=255)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim: str = Field(min_length=1, max_length=1_000)


class ResponseDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str = Field(min_length=1, max_length=200)
    dispute_id: str = Field(min_length=1, max_length=200)
    decision: Decision
    status: DraftStatus = DraftStatus.PENDING_HUMAN_APPROVAL
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20_000)
    citations: list[DraftCitation] = Field(min_length=2, max_length=20)
    generator: str = Field(min_length=1, max_length=100)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    human_approval_required: bool = True


class DraftGenerationError(RuntimeError):
    pass


class EvidenceGroundedDraftGenerator:
    """Create a conservative response using only file-backed verified evidence."""

    def generate(
        self,
        case: DisputeCase,
        assessment: Assessment,
        consistency: EvidenceConsistencyReport | None = None,
        *,
        created_at: datetime | None = None,
    ) -> ResponseDraft:
        if assessment.dispute_id != case.dispute_id:
            raise ValueError("assessment and case dispute IDs must match")
        if assessment.decision != Decision.SAFE_TO_DRAFT:
            raise DraftGenerationError(
                f"case decision is {assessment.decision}; only SAFE_TO_DRAFT can be drafted"
            )

        consistency = consistency or EvidenceConsistencyAnalyzer().analyze(case)
        if consistency.dispute_id != case.dispute_id:
            raise ValueError("consistency report and case dispute IDs must match")
        if consistency.status != ConsistencyStatus.CONSISTENT:
            raise DraftGenerationError("current evidence is not cross-source consistent")
        excluded_ids = set(consistency.excluded_evidence_ids)

        invoice = self._required_file_backed(case, EvidenceType.INVOICE, excluded_ids)
        delivery = self._required_file_backed(
            case, EvidenceType.DELIVERY_PROOF, excluded_ids
        )
        citations = [
            self._citation(
                "E1",
                invoice,
                (
                    f"The verified invoice matches order {case.order_id}, payment "
                    f"{case.payment_id}, and the disputed amount {self._money(case)}."
                ),
            ),
            self._citation(
                "E2",
                delivery,
                (
                    f"The verified delivery record reports delivered status for order "
                    f"{case.order_id}."
                ),
            ),
        ]

        acknowledgement = next(
            (
                document
                for document in case.evidence
                if document.evidence_id not in excluded_ids
                and document.evidence_type == EvidenceType.CUSTOMER_COMMUNICATION
                and document.source_verified
                and document.reviewed_by_human
                and document.customer_acknowledged_delivery is True
                and self._has_file_provenance(document)
            ),
            None,
        )
        if acknowledgement is not None:
            citations.append(
                self._citation(
                    f"E{len(citations) + 1}",
                    acknowledgement,
                    "Verified customer communication acknowledges receipt of the order.",
                )
            )

        subject = f"Evidence response for dispute {case.dispute_id}"
        evidence_lines = "\n".join(
            f"- [{citation.label}] {citation.claim}" for citation in citations
        )
        body = (
            "Draft response - human approval required\n\n"
            f"We request review of dispute {case.dispute_id} for payment "
            f"{case.payment_id}. The payment was captured for order {case.order_id} "
            f"in the amount of {self._money(case)}.\n\n"
            "Supporting evidence:\n"
            f"{evidence_lines}\n\n"
            "The cited files were reviewed by a human and their recorded facts passed "
            "ProofShield's deterministic consistency checks. This draft has not been "
            "submitted and must be approved by an authorized human reviewer."
        )

        input_sha256 = self.input_sha256(case, assessment, consistency)
        content_sha256 = self._sha256(
            {
                "subject": subject,
                "body": body,
                "citations": [citation.model_dump(mode="json") for citation in citations],
            }
        )
        generated_at = created_at or datetime.now(UTC)
        if generated_at.tzinfo is None:
            raise ValueError("created_at must include a timezone")

        return ResponseDraft(
            draft_id=f"draft_{input_sha256[:32]}",
            dispute_id=case.dispute_id,
            decision=assessment.decision,
            subject=subject,
            body=body,
            citations=citations,
            generator=DRAFT_GENERATOR,
            input_sha256=input_sha256,
            content_sha256=content_sha256,
            created_at=generated_at,
        )

    def input_sha256(
        self,
        case: DisputeCase,
        assessment: Assessment,
        consistency: EvidenceConsistencyReport | None = None,
    ) -> str:
        """Fingerprint all evidence and deterministic checks used by a draft."""

        if assessment.dispute_id != case.dispute_id:
            raise ValueError("assessment and case dispute IDs must match")
        consistency = consistency or EvidenceConsistencyAnalyzer().analyze(case)
        if consistency.dispute_id != case.dispute_id:
            raise ValueError("consistency report and case dispute IDs must match")
        input_payload = {
            "generator": DRAFT_GENERATOR,
            "case": case.model_dump(mode="json"),
            "assessment": {
                "decision": assessment.decision,
                "evidence_score": assessment.evidence_score,
                "checks": [
                    {"code": check.code, "outcome": check.outcome}
                    for check in assessment.checks
                ],
            },
            "consistency": consistency.model_dump(mode="json"),
        }
        return self._sha256(input_payload)

    def require_current(
        self,
        case: DisputeCase,
        draft: ResponseDraft,
        assessment: Assessment,
        consistency: EvidenceConsistencyReport,
    ) -> None:
        """Refuse approval or export when a draft predates current case state."""

        if draft.dispute_id != case.dispute_id:
            raise DraftGenerationError("draft belongs to a different case")
        if consistency.dispute_id != case.dispute_id:
            raise DraftGenerationError(
                "consistency report belongs to a different case"
            )
        if consistency.status != ConsistencyStatus.CONSISTENT:
            raise DraftGenerationError(
                "current evidence is not cross-source consistent; reassess and "
                "create a new draft"
            )
        if assessment.decision != Decision.SAFE_TO_DRAFT:
            raise DraftGenerationError(
                f"current case decision is {assessment.decision}; reassess before approval"
            )
        if self.input_sha256(case, assessment, consistency) != draft.input_sha256:
            raise DraftGenerationError(
                "case evidence changed after this draft was created; reassess and "
                "create a new draft"
            )

    @staticmethod
    def _required_file_backed(
        case: DisputeCase,
        evidence_type: EvidenceType,
        excluded_ids: set[str] | None = None,
    ) -> EvidenceDocument:
        excluded_ids = excluded_ids or set()
        document = next(
            (
                item
                for item in case.evidence
                if item.evidence_type == evidence_type
                and item.evidence_id not in excluded_ids
            ),
            None,
        )
        if document is None:
            raise DraftGenerationError(f"required {evidence_type} evidence is missing")
        if not document.source_verified or not document.reviewed_by_human:
            raise DraftGenerationError(
                f"{evidence_type} evidence must be human-reviewed and source-verified"
            )
        if not EvidenceGroundedDraftGenerator._has_file_provenance(document):
            raise DraftGenerationError(
                f"{evidence_type} evidence must be linked to an uploaded file with a hash"
            )
        return document

    @staticmethod
    def _has_file_provenance(document: EvidenceDocument) -> bool:
        return all(
            (document.source_file_id, document.source_name, document.source_sha256)
        )

    @staticmethod
    def _citation(
        label: str, document: EvidenceDocument, claim: str
    ) -> DraftCitation:
        return DraftCitation(
            label=label,
            evidence_id=document.evidence_id,
            evidence_type=document.evidence_type,
            source_file_id=document.source_file_id,
            source_name=document.source_name,
            source_sha256=document.source_sha256,
            claim=claim,
        )

    @staticmethod
    def _money(case: DisputeCase) -> str:
        amount = case.disputed_amount.quantize(Decimal("0.01"))
        return f"{case.currency} {amount:,.2f}"

    @staticmethod
    def _sha256(value: object) -> str:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
