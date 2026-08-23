# Milestone 6: evidence-grounded response drafts

## Outcome

ProofShield can now create a conservative chargeback response draft after, and
only after, the deterministic verifier returns `SAFE_TO_DRAFT`.

The first generator is deliberately deterministic. It does not call an LLM and
does not require model training. This gives the project a reliable baseline and
makes every claim reproducible before optional AI-assisted rewriting is added.

## Safety gate

A draft is refused with HTTP 409 when:

- the verifier returns `NEEDS_REVIEW` or `INSUFFICIENT_EVIDENCE`;
- the invoice or delivery evidence was not reviewed by a human;
- either source is not marked verified; or
- either source is not linked to an uploaded file and SHA-256 hash.

Successful drafts always contain:

- decision `SAFE_TO_DRAFT`;
- status `PENDING_HUMAN_APPROVAL`;
- `human_approval_required=true`;
- at least one invoice citation and one delivery citation;
- source file ID, safe source name, and SHA-256 for every citation; and
- an explicit statement that the draft has not been submitted.

## Idempotency

The generator hashes the complete case state, assessment result, check outcomes,
and generator version. That input hash creates a deterministic draft ID. Retrying
the same case state returns the existing draft with HTTP 200 instead of creating
a second row or history entry.

## Supabase persistence

Migration `20260823170424_response_drafts` adds:

- the RLS-enabled `proofshield_response_drafts` table;
- a composite `(dispute_id, created_at desc, draft_id)` index;
- strict checks allowing only `SAFE_TO_DRAFT` and
  `PENDING_HUMAN_APPROVAL` rows;
- JSON consistency checks for IDs, hashes, citations, status, and human approval;
- the `DRAFT_CREATED` case-history action; and
- the transaction-safe, `SECURITY INVOKER`
  `proofshield_save_response_draft` RPC.

`anon` and `authenticated` have no table or RPC access. The trusted backend has
only `SELECT` and `INSERT` table privileges plus RPC execution; drafts cannot be
updated or deleted through normal application credentials.

## API

- `POST /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts`
- `GET /v1/cases/{dispute_id}/drafts/{draft_id}`

The first POST returns HTTP 201. An idempotent retry returns HTTP 200 with the
same draft.

## Verification

The live test began with a signed Razorpay webhook and confirmed that drafting
was refused before evidence enrichment. After two private file uploads and two
human-confirmed evidence submissions, ProofShield created one draft with invoice
and delivery citations. The retry returned the same draft and created no second
`DRAFT_CREATED` event.

Independent Postgres checks confirmed:

- one case, two evidence records, two file records, and one response draft;
- two matching private Storage objects;
- status `PENDING_HUMAN_APPROVAL` and decision `SAFE_TO_DRAFT`; and
- no `anon` or `authenticated` table/RPC privileges.

All synthetic rows and objects were removed after verification. Final counts
were zero across all seven tables and the private evidence bucket.

## Next milestone

Add an explicit human-review workflow with approve/reject actions and an
exportable evidence packet. Submission to Razorpay remains out of scope until
that approval boundary is implemented and tested.
