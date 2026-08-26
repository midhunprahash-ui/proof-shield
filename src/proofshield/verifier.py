"""Deterministic evidence verification and decision policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from proofshield.consistency import ConsistencyStatus, EvidenceConsistencyAnalyzer
from proofshield.domain import (
    Assessment,
    CheckOutcome,
    Decision,
    DisputeCase,
    DisputeReason,
    EvidenceDocument,
    EvidenceType,
    VerificationCheck,
)

MISSING_EVIDENCE_CODES = {
    "MISSING_INVOICE",
    "MISSING_DELIVERY_PROOF",
    "DEADLINE_PASSED",
    "UNSUPPORTED_REASON",
    "PAYMENT_NOT_CAPTURED",
}


def _check(code: str, outcome: CheckOutcome, message: str) -> VerificationCheck:
    return VerificationCheck(code=code, outcome=outcome, message=message)


def _matching_documents(
    case: DisputeCase, evidence_type: EvidenceType
) -> list[EvidenceDocument]:
    return [document for document in case.evidence if document.evidence_type == evidence_type]


def _money_matches(left: Decimal, right: Decimal) -> bool:
    return left.quantize(Decimal("0.01")) == right.quantize(Decimal("0.01"))


class CaseAssessor:
    """Assess whether evidence is safe to use in a drafted dispute response."""

    def __init__(
        self,
        consistency_analyzer: EvidenceConsistencyAnalyzer | None = None,
    ) -> None:
        self.consistency_analyzer = (
            consistency_analyzer or EvidenceConsistencyAnalyzer()
        )

    def assess(
        self, case: DisputeCase, *, evaluated_at: datetime | None = None
    ) -> Assessment:
        evaluated_at = evaluated_at or datetime.now(UTC)
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must include a timezone")

        checks: list[VerificationCheck] = []
        checks.extend(self._check_scope_and_deadline(case, evaluated_at))
        checks.extend(self._check_payment(case))
        checks.extend(self._check_invoice(case))
        checks.extend(self._check_delivery(case))
        checks.extend(self._check_optional_customer_acknowledgement(case))
        checks.append(self._check_cross_source_consistency(case))

        decision = self._decide(checks)
        passed = sum(check.outcome == CheckOutcome.PASS for check in checks)
        evidence_score = round(passed / len(checks), 4) if checks else 0.0

        summaries = {
            Decision.SAFE_TO_DRAFT: (
                "Required evidence is present and the checked facts are consistent. "
                "A response may be drafted for human approval."
            ),
            Decision.NEEDS_REVIEW: (
                "Evidence exists, but one or more facts conflict or cannot be trusted "
                "without human review."
            ),
            Decision.INSUFFICIENT_EVIDENCE: (
                "The case is missing required evidence, is outside the supported scope, "
                "or can no longer be answered safely."
            ),
        }

        return Assessment(
            dispute_id=case.dispute_id,
            decision=decision,
            evidence_score=evidence_score,
            summary=summaries[decision],
            checks=checks,
            evaluated_at=evaluated_at,
        )

    def _check_cross_source_consistency(
        self,
        case: DisputeCase,
    ) -> VerificationCheck:
        report = self.consistency_analyzer.analyze(case)
        if report.status == ConsistencyStatus.CONSISTENT:
            return _check(
                "CROSS_SOURCE_CONSISTENT",
                CheckOutcome.PASS,
                "Every confirmed evidence record agrees on the checked facts.",
            )
        if report.status == ConsistencyStatus.CONFLICTS_FOUND:
            return _check(
                "CROSS_SOURCE_CONFLICT",
                CheckOutcome.FAIL,
                (
                    f"{report.conflict_count} cross-source fact conflicts require "
                    "operator review before drafting."
                ),
            )
        if report.status == ConsistencyStatus.UNVERIFIED_SOURCES:
            return _check(
                "CROSS_SOURCE_UNVERIFIED",
                CheckOutcome.FAIL,
                (
                    f"{report.unverified_count} evidence sources are unverified; "
                    "all recorded sources must be reviewed before drafting."
                ),
            )
        return _check(
            "CROSS_SOURCE_INCOMPLETE",
            CheckOutcome.FAIL,
            (
                f"{report.missing_count} required source or fact checks are missing "
                "from the complete evidence set."
            ),
        )

    @staticmethod
    def _check_scope_and_deadline(
        case: DisputeCase, evaluated_at: datetime
    ) -> list[VerificationCheck]:
        checks: list[VerificationCheck] = []
        if case.reason == DisputeReason.PRODUCT_NOT_RECEIVED:
            checks.append(
                _check(
                    "SUPPORTED_REASON",
                    CheckOutcome.PASS,
                    "Product-not-received disputes are supported in Milestone 1.",
                )
            )
        else:
            checks.append(
                _check(
                    "UNSUPPORTED_REASON",
                    CheckOutcome.FAIL,
                    "This dispute reason is not supported yet.",
                )
            )

        if case.respond_by <= evaluated_at:
            checks.append(
                _check("DEADLINE_PASSED", CheckOutcome.FAIL, "The response deadline has passed.")
            )
        elif case.respond_by - evaluated_at <= timedelta(hours=24):
            checks.append(
                _check(
                    "DEADLINE_NEAR",
                    CheckOutcome.WARNING,
                    "Less than 24 hours remain; prioritize human review.",
                )
            )
        else:
            checks.append(
                _check("DEADLINE_OPEN", CheckOutcome.PASS, "The response deadline is open.")
            )
        return checks

    @staticmethod
    def _check_payment(case: DisputeCase) -> list[VerificationCheck]:
        checks: list[VerificationCheck] = []
        if not case.payment.captured:
            checks.append(
                _check(
                    "PAYMENT_NOT_CAPTURED",
                    CheckOutcome.FAIL,
                    "The payment is not captured, so this workflow must not draft a contest.",
                )
            )
        else:
            checks.append(
                _check("PAYMENT_CAPTURED", CheckOutcome.PASS, "The payment is captured.")
            )

        if case.payment.payment_id != case.payment_id:
            checks.append(
                _check(
                    "PAYMENT_ID_MISMATCH",
                    CheckOutcome.FAIL,
                    "The dispute and payment record use different payment IDs.",
                )
            )
        else:
            checks.append(
                _check("PAYMENT_ID_MATCH", CheckOutcome.PASS, "The payment IDs match.")
            )

        if case.payment.order_id != case.order_id:
            checks.append(
                _check(
                    "ORDER_ID_MISMATCH",
                    CheckOutcome.FAIL,
                    "The dispute and payment record use different order IDs.",
                )
            )
        else:
            checks.append(_check("ORDER_ID_MATCH", CheckOutcome.PASS, "The order IDs match."))

        amount_matches = _money_matches(case.payment.amount, case.disputed_amount)
        currency_matches = case.payment.currency == case.currency
        if not amount_matches or not currency_matches:
            checks.append(
                _check(
                    "PAYMENT_AMOUNT_MISMATCH",
                    CheckOutcome.FAIL,
                    "The disputed amount or currency does not match the payment record.",
                )
            )
        else:
            checks.append(
                _check(
                    "PAYMENT_AMOUNT_MATCH",
                    CheckOutcome.PASS,
                    "The disputed amount and currency match the payment record.",
                )
            )
        return checks

    @staticmethod
    def _check_invoice(case: DisputeCase) -> list[VerificationCheck]:
        invoices = _matching_documents(case, EvidenceType.INVOICE)
        if not invoices:
            return [
                _check(
                    "MISSING_INVOICE",
                    CheckOutcome.FAIL,
                    "No invoice was supplied for this order.",
                )
            ]

        invoice = invoices[0]
        checks: list[VerificationCheck] = []
        if not invoice.source_verified:
            checks.append(
                _check(
                    "INVOICE_SOURCE_UNVERIFIED",
                    CheckOutcome.FAIL,
                    "The invoice source has not been verified.",
                )
            )
        else:
            checks.append(
                _check(
                    "INVOICE_SOURCE_VERIFIED",
                    CheckOutcome.PASS,
                    "The invoice source is verified.",
                )
            )

        facts_match = (
            invoice.order_id == case.order_id
            and invoice.payment_id == case.payment_id
            and invoice.amount is not None
            and _money_matches(invoice.amount, case.disputed_amount)
        )
        if not facts_match:
            checks.append(
                _check(
                    "INVOICE_FACT_MISMATCH",
                    CheckOutcome.FAIL,
                    "The invoice does not match the order, payment, or disputed amount.",
                )
            )
        else:
            checks.append(
                _check(
                    "INVOICE_FACTS_MATCH",
                    CheckOutcome.PASS,
                    "The invoice matches the order, payment, and disputed amount.",
                )
            )
        return checks

    @staticmethod
    def _check_delivery(case: DisputeCase) -> list[VerificationCheck]:
        proofs = _matching_documents(case, EvidenceType.DELIVERY_PROOF)
        if not proofs:
            return [
                _check(
                    "MISSING_DELIVERY_PROOF",
                    CheckOutcome.FAIL,
                    "No delivery proof was supplied for this order.",
                )
            ]

        proof = proofs[0]
        checks: list[VerificationCheck] = []
        if not proof.source_verified:
            checks.append(
                _check(
                    "DELIVERY_SOURCE_UNVERIFIED",
                    CheckOutcome.FAIL,
                    "The delivery proof source has not been verified.",
                )
            )
        else:
            checks.append(
                _check(
                    "DELIVERY_SOURCE_VERIFIED",
                    CheckOutcome.PASS,
                    "The delivery proof source is verified.",
                )
            )

        if proof.order_id != case.order_id or proof.payment_id not in (None, case.payment_id):
            checks.append(
                _check(
                    "DELIVERY_FACT_MISMATCH",
                    CheckOutcome.FAIL,
                    "The delivery proof belongs to a different order or payment.",
                )
            )
        else:
            checks.append(
                _check(
                    "DELIVERY_FACTS_MATCH",
                    CheckOutcome.PASS,
                    "The delivery proof matches the disputed order.",
                )
            )

        if (proof.delivery_status or "").strip().lower() != "delivered":
            checks.append(
                _check(
                    "NOT_DELIVERED",
                    CheckOutcome.FAIL,
                    "The supplied proof does not show a delivered status.",
                )
            )
        else:
            checks.append(
                _check("DELIVERED", CheckOutcome.PASS, "The carrier status is delivered.")
            )
        return checks

    @staticmethod
    def _check_optional_customer_acknowledgement(
        case: DisputeCase,
    ) -> list[VerificationCheck]:
        messages = _matching_documents(case, EvidenceType.CUSTOMER_COMMUNICATION)
        acknowledged = any(
            message.source_verified and message.customer_acknowledged_delivery is True
            for message in messages
        )
        if acknowledged:
            return [
                _check(
                    "CUSTOMER_ACKNOWLEDGED",
                    CheckOutcome.PASS,
                    "Verified customer communication acknowledges delivery.",
                )
            ]
        return [
            _check(
                "NO_CUSTOMER_ACKNOWLEDGEMENT",
                CheckOutcome.WARNING,
                "No verified customer acknowledgement was found; this is optional evidence.",
            )
        ]

    @staticmethod
    def _decide(checks: list[VerificationCheck]) -> Decision:
        failed_codes = {check.code for check in checks if check.outcome == CheckOutcome.FAIL}
        if failed_codes & MISSING_EVIDENCE_CODES:
            return Decision.INSUFFICIENT_EVIDENCE
        if failed_codes:
            return Decision.NEEDS_REVIEW
        return Decision.SAFE_TO_DRAFT
