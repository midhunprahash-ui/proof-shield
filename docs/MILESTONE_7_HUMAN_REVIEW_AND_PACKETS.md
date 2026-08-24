# Milestone 7: human review and evidence packets

## Outcome

ProofShield now has an explicit final human-review boundary for response drafts.
An authorized local operator can approve or reject one draft exactly once. Only
an approved draft can produce a downloadable evidence packet, and no endpoint
submits anything to Razorpay.

## Operator authorization

The new review and packet endpoints require:

```text
X-ProofShield-Operator-Secret: <backend operator secret>
```

`PROOFSHIELD_OPERATOR_SECRET` must be configured with at least 32 characters.
ProofShield compares the supplied value in constant time. This is a temporary,
backend-only operator gate while the API remains local; it is not a replacement
for named users and Supabase Auth when a frontend is introduced.

`reviewer_label` is therefore an operator-supplied audit label, not a verified
user identity. The operator secret, Supabase secret, and Razorpay secrets must
never enter a frontend bundle or public repository.

## Immutable review rules

- A draft may have exactly one final `APPROVED` or `REJECTED` review.
- A rejection requires a reason.
- Retrying the exact same review returns the stored review without adding a
  second row or history event.
- A changed reviewer, note, or decision conflicts with the immutable result.
- Reviews are stored separately; the original draft remains append-only.
- Approval adds `DRAFT_APPROVED`; rejection adds `DRAFT_REJECTED` to case
  history.

## Evidence-packet rules

`GET /v1/cases/{dispute_id}/drafts/{draft_id}/packet` returns a deterministic
ZIP only after approval. The ZIP contains:

- `manifest.json` with claims, citations, file metadata, and hashes;
- `case.json` with immutable case facts but no uncited evidence records;
- `draft.json` and `response.txt`;
- `review.json`; and
- each cited invoice, delivery, or customer-communication source under
  `evidence/`.

Before writing the ZIP, ProofShield downloads every cited source from private
Supabase Storage and verifies its case, filename, byte count, and SHA-256 against
both the file record and the draft citation. A missing, changed, cross-case, or
inconsistent file fails closed. The response exposes packet and manifest
SHA-256 values in headers so the downloaded artifact can be checked later.

Rejected and unreviewed drafts return HTTP 409 instead of a packet.

## API

- `POST /v1/cases/{dispute_id}/drafts/{draft_id}/reviews`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}/review`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}/packet`

The first review POST returns HTTP 201. An exact retry returns HTTP 200.

## Supabase migration

Migration `20260824070552_draft_reviews_and_evidence_packets` adds the
RLS-enabled, append-only `proofshield_draft_reviews` table and the
`SECURITY INVOKER` `proofshield_review_response_draft` RPC. Browser roles have
no table or RPC privileges; `service_role` receives only table `SELECT`/`INSERT`
and RPC execution.

The RPC derives the dispute from the immutable draft, enforces one review per
draft with an atomic insert, and appends the matching case-history action in the
same transaction.

## Verification status

Local verification currently proves:

- operator authorization fails closed;
- approval/rejection validation and exact-retry idempotency;
- conflicting final reviews are rejected;
- rejected and unreviewed drafts cannot export;
- repeated approved exports are byte-identical;
- ZIP contents and response hashes match; and
- changed evidence bytes are detected before export.

Live migration activation and live Supabase integration verification remain
pending because the current Codex task did not load the already-registered
`supabase-proofshield` MCP tools. Start a new Codex task/session and confirm the
connection before applying this migration. Do not use the unrelated `supabase`
connection.

## Next milestone

After live activation, build the merchant review interface around these APIs.
Razorpay submission remains deliberately out of scope.
