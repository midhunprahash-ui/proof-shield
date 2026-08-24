"""Create deterministic development fixtures for the ProofShield workflow."""

from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from proofshield.domain import (
    Decision,
    DisputeCase,
    DisputeReason,
    EvidenceDocument,
    EvidenceType,
    LabelledSyntheticCase,
    PaymentRecord,
)

SCENARIOS: tuple[tuple[str, Decision], ...] = (
    ("valid_delivery", Decision.SAFE_TO_DRAFT),
    ("valid_delivery_without_customer_message", Decision.SAFE_TO_DRAFT),
    ("missing_delivery_proof", Decision.INSUFFICIENT_EVIDENCE),
    ("expired_deadline", Decision.INSUFFICIENT_EVIDENCE),
    ("order_mismatch", Decision.NEEDS_REVIEW),
    ("amount_mismatch", Decision.NEEDS_REVIEW),
    ("unverified_delivery_source", Decision.NEEDS_REVIEW),
)


def make_case(index: int, scenario: str) -> DisputeCase:
    created_at = datetime(2026, 8, 22, 10, 0, tzinfo=UTC) + timedelta(minutes=index)
    respond_by = created_at + timedelta(days=5)
    amount = Decimal(1000 + (index % 20) * 250)
    payment_id = f"pay_demo_{index:04d}"
    order_id = f"order_demo_{index:04d}"

    payment = PaymentRecord(
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        currency="INR",
        captured=True,
    )
    evidence = [
        EvidenceDocument(
            evidence_id=f"invoice_{index:04d}",
            evidence_type=EvidenceType.INVOICE,
            source_verified=True,
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            issued_at=created_at - timedelta(days=3),
        ),
        EvidenceDocument(
            evidence_id=f"delivery_{index:04d}",
            evidence_type=EvidenceType.DELIVERY_PROOF,
            source_verified=True,
            order_id=order_id,
            payment_id=payment_id,
            issued_at=created_at - timedelta(days=1),
            delivery_status="delivered",
        ),
        EvidenceDocument(
            evidence_id=f"message_{index:04d}",
            evidence_type=EvidenceType.CUSTOMER_COMMUNICATION,
            source_verified=True,
            order_id=order_id,
            payment_id=payment_id,
            customer_acknowledged_delivery=True,
            text="Thank you, I received the order.",
        ),
    ]

    if scenario == "valid_delivery_without_customer_message":
        evidence = [
            item
            for item in evidence
            if item.evidence_type != EvidenceType.CUSTOMER_COMMUNICATION
        ]
    elif scenario == "missing_delivery_proof":
        evidence = [item for item in evidence if item.evidence_type != EvidenceType.DELIVERY_PROOF]
    elif scenario == "expired_deadline":
        respond_by = created_at - timedelta(minutes=1)
    elif scenario == "order_mismatch":
        evidence[1].order_id = "order_different"
    elif scenario == "amount_mismatch":
        evidence[0].amount = amount + Decimal("500")
    elif scenario == "unverified_delivery_source":
        evidence[1].source_verified = False

    return DisputeCase(
        dispute_id=f"disp_demo_{index:04d}",
        reason=DisputeReason.PRODUCT_NOT_RECEIVED,
        payment_id=payment_id,
        order_id=order_id,
        disputed_amount=amount,
        currency="INR",
        created_at=created_at,
        respond_by=respond_by,
        payment=payment,
        evidence=evidence,
    )


def generate_cases(count: int, seed: int = 20260822) -> list[LabelledSyntheticCase]:
    if count < 1:
        raise ValueError("count must be at least 1")
    randomizer = random.Random(seed)
    cases: list[LabelledSyntheticCase] = []
    for index in range(count):
        scenario, expected_decision = randomizer.choice(SCENARIOS)
        cases.append(
            LabelledSyntheticCase(
                scenario=scenario,
                expected_decision=expected_decision,
                case=make_case(index, scenario),
            )
        )
    return cases


def write_jsonl(cases: list[LabelledSyntheticCase], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260822)
    parser.add_argument(
        "--output", type=Path, default=Path("data/synthetic/disputes.jsonl")
    )
    arguments = parser.parse_args()
    cases = generate_cases(arguments.count, arguments.seed)
    write_jsonl(cases, arguments.output)
    print(f"Wrote {len(cases)} deterministic development cases to {arguments.output}")


if __name__ == "__main__":
    main()
