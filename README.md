# ProofShield

ProofShield is a human-approved chargeback evidence responder for merchants.
The first milestone focuses on one dispute class: **product not received**.

When a dispute arrives, ProofShield checks the payment, order, amount, response
deadline, invoice, and delivery evidence. It then returns one of three decisions:

- `SAFE_TO_DRAFT`: the evidence is complete and consistent.
- `NEEDS_REVIEW`: evidence exists, but something important conflicts or cannot
  be trusted automatically.
- `INSUFFICIENT_EVIDENCE`: required evidence is missing, the deadline has
  passed, or the dispute type is not supported yet.

ProofShield only prepares a response. A human must approve any final action.

For `SAFE_TO_DRAFT` cases with human-reviewed, file-backed evidence, ProofShield
can now produce a deterministic response draft with invoice and delivery
citations. The draft is stored as `PENDING_HUMAN_APPROVAL`; it is never submitted
automatically. No model training or LLM call is required for this trusted
baseline.

An active, named Supabase Auth operator can approve or reject that draft once.
The backend verifies the bearer token with Supabase Auth and resolves the
reviewer name from a server-controlled operator registry; the browser cannot
forge the audit identity.
Approval unlocks a deterministic ZIP containing the response, review, manifest,
and cited source files after their Storage bytes pass fresh SHA-256 checks.
Rejection or missing approval blocks export. Razorpay submission is still not
implemented.

The local merchant console is now built with React and bundled by Bun. It gives
the operator one workspace for the dispute queue, evidence upload and reviewed
fact entry, deterministic assessment, cited response drafting, final human
review, packet download, and the append-only audit timeline.

Uploaded JSON and UTF-8 text evidence passes through deterministic labelled-field
extraction. PDF, PNG, and JPEG evidence can now use local PP-OCRv6. OCR proposals
include scores plus exact page and bounding-box references. Proposals are never
verified automatically: the operator must review editable values and explicitly
confirm the source before an append-only evidence record is created. A stable
provider contract keeps a future cloud OCR adapter behind the same API and human
review boundary.

After confirmation, ProofShield compares every structured evidence record instead
of trusting the first invoice or delivery proof. The Evidence tab names missing
requirements, unverified sources, and conflicting IDs, amounts, statuses, or
acknowledgements. The report never decides the chargeback, but deterministic
conflicts and unverified sources now block response drafting until they are
resolved and reassessed.

An authenticated case owner can now resolve an incorrect record without editing
or deleting it. The operator chooses exclusion or a same-type replacement,
records a mandatory reason, and confirms the permanent action. Future checks and
drafts ignore the resolved record, while the original evidence remains visible
in the case and audit trail. Any earlier draft becomes stale. Approved packet
version 3 exports include the immutable resolution audit and its manifest hash.

## Why this architecture

The project intentionally separates two jobs:

- Deterministic code verifies facts that must be exact: IDs, amounts, dates,
  deadlines, delivery status, and document provenance.
- A later AI layer will read messy documents and customer conversations. Its
  extracted claims will still have to pass the deterministic verifier.

This makes the system useful when AI is available and safe when AI is wrong or
unavailable.

## Run locally

ProofShield requires Python 3.12 or newer and the ProofShield Supabase project.
Supabase is the only persistent cloud dependency at this stage; the API and any
future frontend still run locally until deployment is explicitly chosen.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,ocr]'
cp .env.example .env
# Add the backend-only Supabase secret, browser-safe publishable key, and webhook secret.
set -a
source .env
set +a
uvicorn proofshield.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

In a second terminal, start the React merchant console:

```bash
cd frontend
bun install --frozen-lockfile
bun run dev
```

Open `http://localhost:3000`. The frontend uses Supabase only to establish the
operator Auth session; all case data and mutations go through local FastAPI. Its
default API URL is configured by the `proofshield-api-url` meta tag in
`frontend/index.html`. Never place a Supabase secret/service-role key or Razorpay
secret in that file or any frontend source.

Public signup is not available. Create a confirmed Supabase Auth user, then add
the same user ID and normalized email to `proofshield_operators`. The browser
uses the publishable key to sign in, while the backend keeps the Supabase secret
key server-only. See [Milestone 10](docs/MILESTONE_10_OPERATOR_AUTH.md).

The foundation migration is [`supabase/migrations/20260823160507_proofshield_supabase_foundation.sql`](supabase/migrations/20260823160507_proofshield_supabase_foundation.sql).
It is active on project `qoujhmqkjicvcwoiyqkp`.

The human-review and foreign-key-index migrations are also active. A guarded
live-demo runner can verify the complete trusted-backend workflow while making
its synthetic-data retention explicit:

```bash
PYTHONPATH=src python scripts/run_live_demo.py \
  --confirm-live-write \
  --project-ref qoujhmqkjicvcwoiyqkp \
  --label your_unique_demo_label
```

This command requires the backend Supabase configuration plus
`PROOFSHIELD_DEMO_OPERATOR_EMAIL` and `PROOFSHIELD_DEMO_OPERATOR_PASSWORD` for a
provisioned active operator. It refuses a different project reference and does
not print credentials.

The backend accepts `SUPABASE_SECRET_KEY` (preferred) or the legacy
`SUPABASE_SERVICE_ROLE_KEY`. Never expose either value to browser code. The
configured `SUPABASE_PROJECT_REF` must match the hostname in `SUPABASE_URL`, so
ProofShield refuses to start its persistence layer against the wrong project.

## Test

```bash
pytest
cd frontend
bun run check
```

## Generate deterministic example cases

```bash
proofshield-generate --count 60 --output data/synthetic/disputes.jsonl
```

The generator creates development fixtures, not final evaluation evidence. The
held-out evaluation set will be independently reviewed and separated by case
template so near-duplicate documents cannot leak between development and test.

Generate and run the clean synthetic OCR smoke benchmark with:

```bash
python scripts/generate_synthetic_ocr_fixtures.py
python -m proofshield.ocr_evaluation \
  --input data/synthetic/ocr/ocr_cases.jsonl
```

The first run downloads PP-OCRv6 weights to the local PaddleX cache. It does not
upload the benchmark or evidence bytes to an OCR cloud. The three generated
fixtures validate the local integration only; they are not a production-quality
accuracy claim.

## Current API

- `GET /health`
- `GET /ready` (verifies the Supabase persistence path)
- `GET /v1/auth/config` (public URL and publishable key only)
- `GET /v1/auth/me`
- `POST /v1/assessments`
- `POST /v1/webhooks/razorpay`
- `POST /v1/cases`
- `GET /v1/cases`
- `GET /v1/cases/unassigned`
- `POST /v1/cases/{dispute_id}/claim`
- `GET /v1/cases/{dispute_id}`
- `GET /v1/cases/{dispute_id}/consistency`
- `POST /v1/cases/{dispute_id}/files`
- `GET /v1/cases/{dispute_id}/files`
- `POST /v1/cases/{dispute_id}/files/{file_id}/extract`
- `POST /v1/cases/{dispute_id}/evidence`
- `GET /v1/cases/{dispute_id}/resolutions`
- `POST /v1/cases/{dispute_id}/resolutions`
- `POST /v1/cases/{dispute_id}/assessment`
- `POST /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}`
- `POST /v1/cases/{dispute_id}/drafts/{draft_id}/reviews`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}/review`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}/packet`
- `GET /v1/cases/{dispute_id}/history`

The webhook receiver requires:

- `X-Razorpay-Signature`: HMAC-SHA256 over the exact raw request bytes.
- `x-razorpay-event-id`: Razorpay's unique event identifier for duplicate protection.

Every case endpoint, review action, and evidence-packet download requires a
Supabase bearer token for an active operator. Reviews store the verified Auth
user ID and the registry-controlled display name. Webhook cases start
unassigned; an authenticated operator must atomically claim one before its full
workspace becomes accessible.

Webhook idempotency, response-draft idempotency, and append-only audit trails are stored transactionally
in Supabase Postgres. Cases, evidence metadata, structured evidence, and case
history use the same database. Drafts cite only human-reviewed sources linked to
uploaded files and their SHA-256 hashes. Uploaded evidence bytes go to the private
`proofshield-evidence` Supabase Storage bucket under a case-isolated,
server-generated key that does not expose the dispute ID. Only PDF, PNG, JPEG,
JSON, and UTF-8 text files up to 5 MB
are accepted, and the declared content type must match the file bytes.

All ProofShield tables have Row Level Security enabled. The Milestone 10
migration adds read-only, ownership-scoped `authenticated` policies while all
browser mutations remain revoked and backend-only. The React app uses Supabase
Auth directly but never queries the case tables or private evidence bucket.
Remote activation is recorded separately in the milestone document.

This project is **not being deployed now**. Supabase is the initial managed data
platform, but the backend and frontend remain local. Other hosting can be added
later without changing the core evidence rules.

See [the foundation milestone](docs/MILESTONE_1_FOUNDATION.md) for the exact
decision scope. See [the webhook-security milestone](docs/MILESTONE_2_WEBHOOK_SECURITY.md)
for signature verification, idempotency, audit behavior, and limitations. See
[the evidence-store milestone](docs/MILESTONE_3_EVIDENCE_STORE.md) for the full
Supabase-backed case-to-evidence workflow.
See [the Supabase setup guide](docs/SUPABASE_SETUP.md) for the project guard,
migration, environment, and verification steps.
See [Milestone 4](docs/MILESTONE_4_SUPABASE_ACTIVATION.md) for the live-schema
activation and verification record.
See [Milestone 5](docs/MILESTONE_5_LIVE_INTEGRATION.md) for the local Python to
live Supabase integration result. See [Milestone 6](docs/MILESTONE_6_RESPONSE_DRAFTS.md)
for the cited drafting gate, idempotency, persistence, and live verification.
See [Milestone 7](docs/MILESTONE_7_HUMAN_REVIEW_AND_PACKETS.md) for immutable
human decisions, operator authorization, and tamper-evident evidence packets.
See [Milestone 8](docs/MILESTONE_8_MERCHANT_DASHBOARD.md) for the React and Bun
merchant console, browser security boundary, and verification record.
See [Milestone 9](docs/MILESTONE_9_LIVE_REVIEW_DEMO.md) for the live review
migration, guarded synthetic demo, tamper-evident packet, and Supabase audit
verification. See [Milestone 10](docs/MILESTONE_10_OPERATOR_AUTH.md) for named
operators, case ownership, atomic webhook-case claiming, and Auth-aware RLS.
See [Milestone 11](docs/MILESTONE_11_EVIDENCE_EXTRACTION.md) for typed extraction
proposals, the human-confirmation boundary, and the frozen synthetic benchmark.
See [Milestone 12](docs/MILESTONE_12_LOCAL_OCR.md) for local PP-OCRv6 extraction,
page-and-box citations, the cloud-ready provider boundary, and the synthetic scan
benchmark.
See [Milestone 13](docs/MILESTONE_13_EVIDENCE_CONSISTENCY.md) for deterministic
cross-source comparisons, named conflicts and missing facts, and the advisory
operator review boundary.
See [Milestone 14](docs/MILESTONE_14_CONSISTENCY_GATE.md) for all-source drafting
gates, stale-approval refusal, and consistency reports inside evidence packets.
See [Milestone 15](docs/MILESTONE_15_EVIDENCE_RESOLUTION.md) for append-only
evidence corrections, stale-draft invalidation, packet version 3, and the gated
Supabase activation order.
