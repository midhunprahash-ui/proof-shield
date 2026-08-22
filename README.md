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

## Why this architecture

The project intentionally separates two jobs:

- Deterministic code verifies facts that must be exact: IDs, amounts, dates,
  deadlines, delivery status, and document provenance.
- A later AI layer will read messy documents and customer conversations. Its
  extracted claims will still have to pass the deterministic verifier.

This makes the system useful when AI is available and safe when AI is wrong or
unavailable.

## Run locally

ProofShield requires Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn proofshield.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the interactive API documentation.

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
- `POST /v1/assessments`
- `POST /v1/webhooks/razorpay`
- `POST /v1/cases`
- `GET /v1/cases`
- `GET /v1/cases/{dispute_id}`
- `POST /v1/cases/{dispute_id}/files`
- `GET /v1/cases/{dispute_id}/files`
- `POST /v1/cases/{dispute_id}/evidence`
- `POST /v1/cases/{dispute_id}/assessment`
- `GET /v1/cases/{dispute_id}/history`

The webhook endpoint is local-only. It requires:

- `X-Razorpay-Signature`: HMAC-SHA256 over the exact raw request bytes.
- `x-razorpay-event-id`: Razorpay's unique event identifier for duplicate protection.

Accepted events are recorded in an append-only local JSONL ledger. The default
path is `data/runtime/webhook_audit.jsonl`, which is intentionally ignored by Git
because real webhook records can contain sensitive merchant and customer data.

Cases, evidence metadata, and history are stored in local SQLite. Uploaded
evidence is stored by its SHA-256 content hash under `data/runtime/evidence`.
Only PDF, PNG, JPEG, JSON, and UTF-8 text files up to 5 MB are accepted, and the
declared content type must match the file bytes.

This project is **not being deployed now**. We will consider deployment only
after the local product, evaluation, and demo are complete.

See [the foundation milestone](docs/MILESTONE_1_FOUNDATION.md) for the exact
decision scope. See [the webhook-security milestone](docs/MILESTONE_2_WEBHOOK_SECURITY.md)
for signature verification, idempotency, audit behavior, and limitations. See
[the evidence-store milestone](docs/MILESTONE_3_EVIDENCE_STORE.md) for the full
local case-to-evidence workflow.
