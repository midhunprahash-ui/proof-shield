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
       |
       v
Named Supabase Auth operator review
  - bearer token verified by Supabase Auth
  - active operator registry controls display name
  - verified user ID written to immutable review
  - immutable APPROVED or REJECTED decision
  - exact retries are idempotent
  - no automatic submission
       |
       v
Approved -> tamper-evident evidence ZIP
Rejected -> no export
       ^
       |
React merchant console (Bun bundle)
  - Supabase Auth session only
  - all case data goes through local FastAPI
  - publishable key is browser-safe; secret key stays backend-only
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
       |
       v
Unassigned merchant queue -> one active operator claims atomically
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
Provider-independent extraction proposal
  - deterministic labels for JSON and UTF-8 text
  - local PP-OCRv6 for PDF, PNG and JPEG
  - JSON pointer, text line, or OCR page-and-box reference per field
  - score is not a calibrated probability
  - cannot mark evidence as verified
       |
       v
Human reviews, edits and explicitly confirms structured facts
       |
       v
Evidence ID + source file linked to exactly one dispute
       |
       v
Append-only evidence resolution when needed
  - original record and file remain visible
  - incorrect records are excluded from future checks
  - superseded records require a same-type replacement
  - verified operator identity and reason are retained
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
Document extraction provider
  - deterministic labelled fields for JSON/text
  - local PP-OCRv6 for PDF/images
  - stable provider contract for an optional cloud adapter later
       |
       v
Advisory cross-source consistency analyzer
  - compares every confirmed evidence record
  - names conflicts, missing facts and unverified sources
  - calculated on demand; never approves or persists a chargeback decision
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

Any extraction component may propose facts, but it cannot mark its own claims as
verified. Source verification comes from an explicit human confirmation or a
future trusted integration adapter.
The consistency analyzer reads only structured, confirmed evidence records and
returns a derived report. The report never decides a chargeback, but the
deterministic verifier maps conflicts, missing required facts, and unverified
sources to failed draft-readiness checks. A later conflicting record therefore
cannot be hidden behind the first invoice or delivery proof.
The deterministic verifier remains the final gate before a response can be
drafted. Final submission always requires a human.

## Current cloud boundary

Supabase is currently the only cloud system. It provides Postgres, transaction-safe
webhook idempotency, append-only audit/history tables, and a private evidence
bucket. The API and frontend are not deployed. This keeps today’s architecture
simple while allowing either component to be hosted elsewhere later.

OCR runs inside the local FastAPI process after a backend-only read from private
Storage and a fresh SHA-256 check. The current PaddleOCR provider is replaceable;
a future cloud provider must remain backend-only and return the same located,
unverified observations. Changing providers cannot weaken case ownership,
provenance checks, or human confirmation.

All public-schema ProofShield tables use RLS. The operator-auth migration adds
read-only policies that require an active registry row and case ownership.
Authenticated browser roles receive no insert, update, or delete grants. All
mutations stay behind FastAPI and its backend-only Supabase secret key.

Response drafts use the same boundary. They are append-only through the trusted
backend, transactionally add one `DRAFT_CREATED` history event, and cannot be
read directly by browser roles.

Draft reviews are also append-only and backend-only. The local API verifies the
Supabase access token and active operator row before allowing review actions or
raw evidence downloads. Approval does not submit a response; it only unlocks a
deterministic ZIP whose cited Storage objects are re-hashed before inclusion.
The caller cannot supply the reviewer label; the backend stamps the verified
Auth user ID and registry-controlled display name.

Packet export re-runs consistency and assessment against the current active
evidence set. Any evidence addition or resolution after drafting changes the
deterministic input fingerprint and invalidates the old approval. Version 3
packets include hashed `consistency-report.json` and
`evidence-resolutions.json` files whose digests are sealed into the manifest.

## Current frontend boundary

```text
React + TypeScript merchant console
       |
       | publishable key: Supabase Auth session only
       | bearer token over local HTTP, restricted CORS origins
       v
FastAPI validation and authorization
       |
       | backend-only secret key
       v
Supabase Postgres + private Storage
```

The browser can sign in, claim an unassigned webhook case, list only owned
cases, upload a reviewed source, add structured evidence, record an immutable
evidence resolution,
run the verifier, create a cited draft, record one protected human decision,
download an approved packet, and view case history. It cannot access Supabase
tables or Storage directly and it cannot submit a response to Razorpay.
