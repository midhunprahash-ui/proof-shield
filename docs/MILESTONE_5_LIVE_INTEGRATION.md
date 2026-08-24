# Milestone 5: live Python integration

## Outcome

The local FastAPI application successfully completed a real end-to-end workflow
against Supabase project `qoujhmqkjicvcwoiyqkp`. Nothing was deployed; Supabase
remained the only cloud dependency.

The verified path was:

1. start the local API with backend-only Supabase configuration;
2. accept a signed synthetic Razorpay dispute webhook;
3. acknowledge an identical retry without repeating work;
4. upload an invoice and delivery record to private Supabase Storage;
5. attach human-reviewed structured facts to both files;
6. reassess the case as `SAFE_TO_DRAFT`;
7. inspect the ordered case and webhook history;
8. remove every synthetic database row and Storage object.

## Live result

- `/health` and `/ready` returned HTTP 200 with Supabase persistence active.
- The webhook moved from `RECEIVED` to `PROCESSED`; its retry recorded
  `DUPLICATE`.
- Two file records, two structured evidence records, two Storage objects, and
  seven case-history entries matched independently queried Postgres state.
- Human approval remained required even when the case became safe to draft.
- Final counts were zero for all ProofShield tables and the private bucket.

This proved the Python client, Data API, transaction-safe RPCs, Postgres tables,
and Storage API work together without relying on mocks or a deployment.
