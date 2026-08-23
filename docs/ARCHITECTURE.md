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
Evidence-grounded draft gate
  - only SAFE_TO_DRAFT
  - human-reviewed file provenance required
  - invoice and delivery claims carry citations
  - deterministic input/content hashes
       |
       v
PENDING_HUMAN_APPROVAL
  - no automatic submission
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
x-razorpay-event-id transaction in Supabase Postgres
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
Append-only Supabase audit record
```

## Current evidence flow

```text
Verified webhook or manually created case
       |
       v
Supabase Postgres case record (core facts are immutable)
       |
       v
Upload evidence source to private Supabase Storage
  - PDF / PNG / JPEG / JSON / UTF-8 text
  - maximum 5 MB
  - filename reduced to a safe label
  - bytes checked against declared content type
  - case-isolated server key includes the SHA-256 hash
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
Verified webhook event
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

## Current cloud boundary

Supabase is currently the only cloud system. It provides Postgres, transaction-safe
webhook idempotency, append-only audit/history tables, and a private evidence
bucket. The API and frontend are not deployed. This keeps today’s architecture
simple while allowing either component to be hosted elsewhere later.

All public-schema ProofShield tables use RLS with no browser-facing policies.
Only backend code holding the Supabase secret/service-role key can access them.
That key must never enter the frontend. When user accounts are introduced, the
schema will gain explicit ownership columns and narrowly scoped policies rather
than opening the current backend tables directly.

Response drafts use the same boundary. They are append-only through the trusted
backend, transactionally add one `DRAFT_CREATED` history event, and cannot be
read directly by browser roles.
