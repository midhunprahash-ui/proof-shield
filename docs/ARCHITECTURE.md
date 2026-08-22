# ProofShield architecture

## Current vertical slice

```text
Dispute case JSON
       |
       v
Pydantic input contract
       |
       v
Deterministic checks
  - supported reason
  - response deadline
  - captured payment
  - payment/order/amount match
  - verified invoice
  - verified delivery proof
       |
       v
Decision policy
  - SAFE_TO_DRAFT
  - NEEDS_REVIEW
  - INSUFFICIENT_EVIDENCE
       |
       v
Structured checks + plain-language summary
       |
       v
Human approval remains mandatory
```

## Planned complete flow

```text
Razorpay dispute webhook
       |
       v
Raw-body signature verification + idempotent event storage
       |
       v
Payment, order and merchant-evidence adapters
       |
       v
AI document extraction
       |
       v
Deterministic verifier (current milestone)
       |
       v
Policy engine -> response draft or abstention
       |
       v
Human approval -> Razorpay draft action
       |
       v
Immutable audit trail and outcome evaluation
```

## Safety boundary

The future AI component may propose extracted facts, but it cannot mark its own
claims as verified. Source verification comes from trusted integration adapters.
The deterministic verifier remains the final gate before a response can be
drafted. Final submission always requires a human.
