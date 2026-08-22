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

## Current webhook flow

```text
Raw Razorpay-compatible webhook bytes
       |
       v
1 MB local size gate
       |
       v
HMAC-SHA256 verification over the untouched bytes
       |
       v
x-razorpay-event-id claim
  - new event -> continue
  - same ID + same body -> acknowledge duplicate
  - same ID + changed body -> reject conflict
       |
       v
Official-payload-compatible Pydantic contract
       |
       v
Razorpay payload adapter -> deterministic verifier
       |
       v
Append-only local audit record
```

## Current evidence flow

```text
Verified webhook or manually created case
       |
       v
SQLite case record (core facts are immutable)
       |
       v
Upload local evidence source
  - PDF / PNG / JPEG / JSON / UTF-8 text
  - maximum 5 MB
  - filename reduced to a safe label
  - bytes checked against declared content type
  - stored by SHA-256 hash
       |
       v
Human reviews the source and enters structured facts
       |
       v
Evidence ID + source file linked to exactly one dispute
       |
       v
Deterministic reassessment
       |
       v
Append-only case history
```

## Planned complete flow

```text
Verified local webhook event
       |
       v
Payment, order and merchant-evidence adapters
       |
       v
AI document extraction
       |
       v
Deterministic verifier
       |
       v
Policy engine -> response draft or abstention
       |
       v
Human approval -> optional Razorpay draft action later
       |
       v
Outcome evaluation
```

## Safety boundary

The future AI component may propose extracted facts, but it cannot mark its own
claims as verified. Source verification comes from trusted integration adapters.
The deterministic verifier remains the final gate before a response can be
drafted. Final submission always requires a human.

## Local-only boundary

The current event ledger is designed for one local application process. It is
durable across restarts but is not a replacement for a transactional database
or queue in a distributed deployment. We are deliberately postponing those
systems until deployment is actually needed.
