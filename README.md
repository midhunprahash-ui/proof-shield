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
python -m pip install -e '.[dev]'
cp .env.example .env
# Add the backend-only Supabase secret key and Razorpay webhook secret to .env.
set -a
source .env
set +a
uvicorn proofshield.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.
The foundation migration is [`supabase/migrations/20260823160507_proofshield_supabase_foundation.sql`](supabase/migrations/20260823160507_proofshield_supabase_foundation.sql).
It is active on project `qoujhmqkjicvcwoiyqkp`.

The backend accepts `SUPABASE_SECRET_KEY` (preferred) or the legacy
`SUPABASE_SERVICE_ROLE_KEY`. Never expose either value to browser code. The
configured `SUPABASE_PROJECT_REF` must match the hostname in `SUPABASE_URL`, so
ProofShield refuses to start its persistence layer against the wrong project.

## Test

```bash
pytest
```

## Generate deterministic example cases

```bash
proofshield-generate --count 60 --output data/synthetic/disputes.jsonl
```

The generator creates development fixtures, not final evaluation evidence. The
held-out evaluation set will be independently reviewed and separated by case
template so near-duplicate documents cannot leak between development and test.

## Current API

- `GET /health`
- `GET /ready` (verifies the Supabase persistence path)
- `POST /v1/assessments`
- `POST /v1/webhooks/razorpay`
- `POST /v1/cases`
- `GET /v1/cases`
- `GET /v1/cases/{dispute_id}`
- `POST /v1/cases/{dispute_id}/files`
- `GET /v1/cases/{dispute_id}/files`
- `POST /v1/cases/{dispute_id}/evidence`
- `POST /v1/cases/{dispute_id}/assessment`
- `POST /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}`
- `GET /v1/cases/{dispute_id}/history`

The webhook receiver requires:

- `X-Razorpay-Signature`: HMAC-SHA256 over the exact raw request bytes.
- `x-razorpay-event-id`: Razorpay's unique event identifier for duplicate protection.

Webhook idempotency, response-draft idempotency, and append-only audit trails are stored transactionally
in Supabase Postgres. Cases, evidence metadata, structured evidence, and case
history use the same database. Drafts cite only human-reviewed sources linked to
uploaded files and their SHA-256 hashes. Uploaded evidence bytes go to the private
`proofshield-evidence` Supabase Storage bucket under a case-isolated,
server-generated key that does not expose the dispute ID. Only PDF, PNG, JPEG,
JSON, and UTF-8 text files up to 5 MB
are accepted, and the declared content type must match the file bytes.

All ProofShield tables have Row Level Security enabled. There are deliberately
no `anon` or `authenticated` policies yet; only the trusted backend can access
them. Frontend access will be designed later alongside user ownership and Auth.

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
