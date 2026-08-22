# Milestone 2: local webhook security and audit trail

## What works now

ProofShield accepts a Razorpay-compatible `payment.dispute.created` webhook at:

```text
POST /v1/webhooks/razorpay
```

Before reading any business fields, it:

1. Keeps the original request bytes unchanged.
2. Limits the local request body to one megabyte.
3. Calculates HMAC-SHA256 using `RAZORPAY_WEBHOOK_SECRET`.
4. Compares the expected and received signatures in constant time.
5. Requires `x-razorpay-event-id` for idempotency.
6. Rejects an event ID if it is reused with a different signed body.
7. Validates the signed JSON against a minimal official-payload-compatible contract.
8. Adapts payment amounts from currency subunits to major units.
9. Sends the resulting case through the deterministic evidence verifier.
10. Appends the result to a local JSONL audit ledger.

This follows Razorpay's current guidance:

- Signature validation: https://razorpay.com/docs/webhooks/validate-test/
- Dispute payloads: https://razorpay.com/docs/webhooks/disputes/
- Webhook best practices: https://razorpay.com/docs/webhooks/best-practices/

## Why raw bytes matter

Two JSON documents can represent the same values while using different spaces
or key order. Their bytes—and therefore their HMAC signatures—are different.
ProofShield verifies the raw request first and parses JSON only after the
signature succeeds.

## Duplicate behavior

Razorpay can deliver the same event more than once. ProofShield uses the
`x-razorpay-event-id` header and body SHA-256 digest:

- Same event ID and same body: return success without running the workflow again.
- Same event ID and a different body: reject the conflict.
- A failed, incomplete event may be retried.
- A completed event remains protected after a local restart.

Rejected signature attempts are audited but never reserve their supplied event
ID. This prevents an attacker from blocking a later legitimate event by sending
the ID first with an invalid signature.

## Audit statuses

- `RECEIVED`: signature verified and processing began.
- `PROCESSED`: event was adapted and assessed.
- `DUPLICATE`: event was already completed and was not processed again.
- `IGNORED`: authentic event is outside the current workflow.
- `NEEDS_ENRICHMENT`: authentic event lacks required order data.
- `FAILED`: authentic event could not be processed and may be retried.
- `REJECTED`: signature, payload, or event-ID security check failed.

The ledger defaults to `data/runtime/webhook_audit.jsonl`. It is not committed.

## Important limitation

A dispute-created webhook does not contain the merchant's invoice, courier
record, or customer conversation. Therefore a successfully received event will
normally produce `INSUFFICIENT_EVIDENCE` until the next milestone enriches it
with trusted local evidence.

That is the honest result. ProofShield does not invent evidence just to produce
a successful-looking demo.

## Local-only status

Nothing is deployed and no external webhook is configured. The ledger is safe
for a single local process and local demonstrations. A future deployment would
replace it with transactional storage plus a background queue and would add
infrastructure-level request limits and network controls.

## Verification coverage

Automated tests cover:

- valid signatures;
- changed raw bytes;
- missing and malformed signatures;
- forged signatures;
- duplicate delivery;
- persistence across restart;
- event-ID/body conflicts;
- retry after failure;
- malformed signed payloads;
- unsupported events;
- missing order IDs;
- amount conversion;
- absent webhook configuration.

## Next milestone

Create a trusted local merchant evidence store with invoices, delivery proofs,
and customer conversations. Then connect document extraction behind the
deterministic safety boundary.

This evidence-store milestone is now implemented and documented in
`MILESTONE_3_EVIDENCE_STORE.md`.
