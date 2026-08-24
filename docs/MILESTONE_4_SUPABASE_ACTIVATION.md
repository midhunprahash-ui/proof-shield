# Milestone 4: Supabase foundation activation

## Outcome

ProofShield's persistence foundation is active on Supabase project
`qoujhmqkjicvcwoiyqkp`. Supabase is the only cloud platform in use. The API and
frontend are still local and nothing was deployed.

Supabase records the migration as:

```text
20260823160507 proofshield_supabase_foundation
```

The matching repository source is:

```text
supabase/migrations/20260823160507_proofshield_supabase_foundation.sql
```

## Live resources

Postgres contains six empty, RLS-enabled tables:

- `proofshield_cases`
- `proofshield_evidence`
- `proofshield_evidence_files`
- `proofshield_case_history`
- `proofshield_webhook_events`
- `proofshield_webhook_audit`

Nine `SECURITY INVOKER` RPCs provide transaction-safe case, evidence, history,
and webhook operations. Every foreign-key/read path required by the current API
has an index.

The private `proofshield-evidence` Storage bucket accepts only PDF, PNG, JPEG,
JSON, and UTF-8 text files up to 5 MB.

## Access boundary

`anon` and `authenticated` have no table or RPC privileges. No browser-facing
RLS or Storage policies exist. `service_role` has only the table operations and
RPC execution needed by the trusted backend.

The project already contained an automatic RLS event trigger. Its
`SECURITY DEFINER` function had been callable by public roles; the migration
revoked `PUBLIC`, `anon`, and `authenticated` execution without disabling the
trigger.

This is deliberate backend-only architecture. A future frontend must never
receive the Supabase secret/service-role key. Auth, ownership columns, and
narrow RLS policies must be designed before any direct frontend data access.

## Live verification

A synthetic service-role test confirmed:

- first case insert returns `CREATED`;
- an identical replay returns `EXISTS`;
- the same dispute ID with changed core facts returns `CONFLICT`;
- file metadata, structured evidence, assessment, and ordered history are
  transactionally consistent;
- webhook state reaches `PROCESSED`;
- the webhook audit sequence records `RECEIVED`, `DUPLICATE`, `REJECTED`,
  `PROCESSED`, and a final `DUPLICATE` exactly as expected.

Evidence/history and webhook tests ran inside rolled-back transactions. The one
persisted synthetic case used to verify replay behavior was deleted afterward.
Final counts were zero for all six tables and the evidence bucket.

## Advisor result

Supabase security advisors report no warnings or errors. Informational notices
that RLS tables have no policies are expected because browser roles are denied.

Performance advisors only report two new indexes as unused. This is expected
while the database is empty; removing them now would weaken the planned list
and webhook-status query paths.

## Next milestone

Add backend configuration and run the FastAPI application locally against the
live Supabase project. Then exercise one full API flow:

1. create a synthetic case;
2. upload a synthetic evidence file through Supabase Storage;
3. attach reviewed structured evidence;
4. assess the case and inspect history;
5. clean up the synthetic case and object.

This validates Python client -> Data API -> Postgres/Storage behavior without
deploying the backend or frontend.
