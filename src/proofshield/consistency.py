"""Deterministic, advisory comparison of facts across evidence sources."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from proofshield.domain import DisputeCase, EvidenceDocument, EvidenceType
from proofshield.resolution import EvidenceResolution


class ConsistencyStatus(StrEnum):
    CONSISTENT = "CONSISTENT"
    CONFLICTS_FOUND = "CONFLICTS_FOUND"
    INCOMPLETE = "INCOMPLETE"
    UNVERIFIED_SOURCES = "UNVERIFIED_SOURCES"


class RequirementOutcome(StrEnum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"
    OPTIONAL = "OPTIONAL"


class FactOutcome(StrEnum):
    MATCH = "MATCH"
    CONFLICT = "CONFLICT"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


class ConsistencyField(StrEnum):
    ORDER_ID = "order_id"
    PAYMENT_ID = "payment_id"
    AMOUNT = "amount"
    DELIVERY_STATUS = "delivery_status"
    CUSTOMER_ACKNOWLEDGED_DELIVERY = "customer_acknowledged_delivery"


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: EvidenceType
    required: bool
    outcome: RequirementOutcome
    record_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    unverified_evidence_ids: list[str]
    message: str


class FactObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: EvidenceType
    source_name: str | None
    source_verified: bool
    value: str | bool
    matches_expected: bool | None


class FactComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: ConsistencyField
    expected_value: str | bool | None
    outcome: FactOutcome
    observations: list[FactObservation]
    missing_from_evidence_ids: list[str]
    message: str


class EvidenceConsistencyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dispute_id: str
    status: ConsistencyStatus
    summary: str
    requirements: list[EvidenceRequirement]
    facts: list[FactComparison]
    conflict_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    unverified_count: int = Field(ge=0)
    resolution_count: int = Field(ge=0)
    excluded_evidence_ids: list[str]
    active_evidence_ids: list[str]
    advisory_only: Literal[True] = True
    human_review_required: Literal[True] = True


@dataclass(frozen=True)
class _FactRule:
    field: ConsistencyField
    evidence_types: frozenset[EvidenceType]
    required_in: frozenset[EvidenceType]
    expected_value: str | bool | None


class EvidenceConsistencyAnalyzer:
    """Compare every recorded source without changing case or assessment state."""

    _requirements = (
        (EvidenceType.INVOICE, True),
        (EvidenceType.DELIVERY_PROOF, True),
        (EvidenceType.CUSTOMER_COMMUNICATION, False),
    )

    def analyze(
        self,
        case: DisputeCase,
        resolutions: Iterable[EvidenceResolution] = (),
    ) -> EvidenceConsistencyReport:
        resolution_list = list(resolutions)
        if any(item.dispute_id != case.dispute_id for item in resolution_list):
            raise ValueError("every resolution must belong to the analyzed case")
        excluded_ids = {item.evidence_id for item in resolution_list}
        active_evidence = [
            document
            for document in case.evidence
            if document.evidence_id not in excluded_ids
        ]
        requirements = [
            self._requirement(active_evidence, evidence_type, required=required)
            for evidence_type, required in self._requirements
        ]
        rules = (
            _FactRule(
                field=ConsistencyField.ORDER_ID,
                evidence_types=frozenset(EvidenceType),
                required_in=frozenset(
                    {EvidenceType.INVOICE, EvidenceType.DELIVERY_PROOF}
                ),
                expected_value=case.order_id,
            ),
            _FactRule(
                field=ConsistencyField.PAYMENT_ID,
                evidence_types=frozenset(EvidenceType),
                required_in=frozenset({EvidenceType.INVOICE}),
                expected_value=case.payment_id,
            ),
            _FactRule(
                field=ConsistencyField.AMOUNT,
                evidence_types=frozenset({EvidenceType.INVOICE}),
                required_in=frozenset({EvidenceType.INVOICE}),
                expected_value=_money(case.disputed_amount),
            ),
            _FactRule(
                field=ConsistencyField.DELIVERY_STATUS,
                evidence_types=frozenset({EvidenceType.DELIVERY_PROOF}),
                required_in=frozenset({EvidenceType.DELIVERY_PROOF}),
                expected_value="delivered",
            ),
            _FactRule(
                field=ConsistencyField.CUSTOMER_ACKNOWLEDGED_DELIVERY,
                evidence_types=frozenset({EvidenceType.CUSTOMER_COMMUNICATION}),
                required_in=frozenset(),
                expected_value=None,
            ),
        )
        facts = [
            comparison
            for rule in rules
            if (comparison := self._compare_fact(active_evidence, rule)) is not None
        ]

        conflict_count = sum(fact.outcome == FactOutcome.CONFLICT for fact in facts)
        missing_count = sum(
            requirement.outcome == RequirementOutcome.MISSING
            for requirement in requirements
        ) + sum(fact.outcome == FactOutcome.MISSING for fact in facts)
        unverified_ids = {
            document.evidence_id
            for document in active_evidence
            if not document.source_verified
        }
        status = self._status(
            conflict_count=conflict_count,
            missing_count=missing_count,
            unverified_count=len(unverified_ids),
        )
        return EvidenceConsistencyReport(
            dispute_id=case.dispute_id,
            status=status,
            summary=self._summary(status),
            requirements=requirements,
            facts=facts,
            conflict_count=conflict_count,
            missing_count=missing_count,
            unverified_count=len(unverified_ids),
            resolution_count=len(resolution_list),
            excluded_evidence_ids=sorted(excluded_ids),
            active_evidence_ids=sorted(
                document.evidence_id for document in active_evidence
            ),
        )

    @staticmethod
    def _requirement(
        evidence: list[EvidenceDocument],
        evidence_type: EvidenceType,
        *,
        required: bool,
    ) -> EvidenceRequirement:
        documents = [
            document for document in evidence if document.evidence_type == evidence_type
        ]
        unverified = sorted(
            document.evidence_id
            for document in documents
            if not document.source_verified
        )
        verified_count = len(documents) - len(unverified)
        if not documents:
            outcome = RequirementOutcome.MISSING if required else RequirementOutcome.OPTIONAL
            message = (
                f"Required {_evidence_label(evidence_type)} evidence is missing."
                if required
                else "Customer communication is optional and has not been supplied."
            )
        elif unverified:
            outcome = RequirementOutcome.UNVERIFIED
            message = (
                f"{len(unverified)} of {len(documents)} "
                f"{_evidence_label(evidence_type)} "
                "records use an unverified source."
            )
        else:
            outcome = RequirementOutcome.SATISFIED
            message = (
                f"All {len(documents)} {_evidence_label(evidence_type)} records have "
                "human-verified sources."
            )
        return EvidenceRequirement(
            evidence_type=evidence_type,
            required=required,
            outcome=outcome,
            record_count=len(documents),
            verified_count=verified_count,
            unverified_evidence_ids=unverified,
            message=message,
        )

    def _compare_fact(
        self,
        evidence: list[EvidenceDocument],
        rule: _FactRule,
    ) -> FactComparison | None:
        relevant = [
            document
            for document in evidence
            if document.evidence_type in rule.evidence_types
        ]
        if not relevant and not rule.required_in:
            return None

        observations: list[FactObservation] = []
        missing_from: list[str] = []
        required_type_absent = any(
            not any(document.evidence_type == evidence_type for document in evidence)
            for evidence_type in rule.required_in
        )
        expected_normalized = self._normalize(rule.field, rule.expected_value)
        normalized_observations: list[str | bool] = []
        for document in relevant:
            raw_value = getattr(document, rule.field.value)
            if raw_value is None:
                if document.evidence_type in rule.required_in:
                    missing_from.append(document.evidence_id)
                continue
            displayed_value = self._display(rule.field, raw_value)
            normalized_value = self._normalize(rule.field, raw_value)
            normalized_observations.append(normalized_value)
            observations.append(
                FactObservation(
                    evidence_id=document.evidence_id,
                    evidence_type=document.evidence_type,
                    source_name=document.source_name,
                    source_verified=document.source_verified,
                    value=displayed_value,
                    matches_expected=(
                        normalized_value == expected_normalized
                        if expected_normalized is not None
                        else None
                    ),
                )
            )

        has_conflict = (
            any(value != expected_normalized for value in normalized_observations)
            if expected_normalized is not None
            else len(set(normalized_observations)) > 1
        )
        if has_conflict:
            outcome = FactOutcome.CONFLICT
            message = "Recorded sources disagree with the trusted case facts or each other."
        elif required_type_absent or missing_from:
            outcome = FactOutcome.MISSING
            message = "A required evidence source does not contain this fact."
        elif any(not observation.source_verified for observation in observations):
            outcome = FactOutcome.UNVERIFIED
            message = "The recorded values agree, but at least one source is unverified."
        else:
            outcome = FactOutcome.MATCH
            message = (
                "Every recorded value agrees with the expected fact."
                if expected_normalized is not None
                else "Every recorded source agrees on this optional fact."
            )

        return FactComparison(
            field=rule.field,
            expected_value=rule.expected_value,
            outcome=outcome,
            observations=observations,
            missing_from_evidence_ids=sorted(missing_from),
            message=message,
        )

    @staticmethod
    def _normalize(field: ConsistencyField, value: Any) -> str | bool | None:
        if value is None:
            return None
        if field == ConsistencyField.AMOUNT:
            return _money(Decimal(str(value)))
        if field == ConsistencyField.DELIVERY_STATUS:
            return str(value).strip().casefold()
        if field == ConsistencyField.CUSTOMER_ACKNOWLEDGED_DELIVERY:
            return bool(value)
        return str(value).strip()

    @staticmethod
    def _display(field: ConsistencyField, value: Any) -> str | bool:
        if field == ConsistencyField.AMOUNT:
            return _money(Decimal(str(value)))
        if field == ConsistencyField.CUSTOMER_ACKNOWLEDGED_DELIVERY:
            return bool(value)
        return str(value)

    @staticmethod
    def _status(
        *,
        conflict_count: int,
        missing_count: int,
        unverified_count: int,
    ) -> ConsistencyStatus:
        if conflict_count:
            return ConsistencyStatus.CONFLICTS_FOUND
        if missing_count:
            return ConsistencyStatus.INCOMPLETE
        if unverified_count:
            return ConsistencyStatus.UNVERIFIED_SOURCES
        return ConsistencyStatus.CONSISTENT

    @staticmethod
    def _summary(status: ConsistencyStatus) -> str:
        return {
            ConsistencyStatus.CONSISTENT: (
                "Required evidence is present and every recorded fact agrees."
            ),
            ConsistencyStatus.CONFLICTS_FOUND: (
                "One or more recorded facts conflict. An operator must inspect the "
                "named sources before relying on them."
            ),
            ConsistencyStatus.INCOMPLETE: (
                "Required evidence or required facts are missing."
            ),
            ConsistencyStatus.UNVERIFIED_SOURCES: (
                "Recorded facts agree, but at least one source is not human verified."
            ),
        }[status]


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _evidence_label(evidence_type: EvidenceType) -> str:
    return evidence_type.value.replace("_", " ").lower()
