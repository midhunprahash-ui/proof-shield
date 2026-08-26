# Supabase setup for ProofShield

## Project boundary

ProofShield uses Supabase project `qoujhmqkjicvcwoiyqkp`.

The MCP connection is named `supabase-proofshield` because this computer
already had a `supabase` MCP connection for a different project. Keeping both
names prevents an accidental schema change in the unrelated project.

In the development client's MCP settings, confirm `supabase-proofshield` is
authenticated and its URL contains the exact project reference above. MCP
servers added during an existing task may load only in the next task/session.

## Applied repository migrations

The source-of-truth migrations are:

```text
supabase/migrations/20260823160507_proofshield_supabase_foundation.sql
supabase/migrations/20260823170424_response_drafts.sql
supabase/migrations/20260824070552_draft_reviews_and_evidence_packets.sql
supabase/migrations/20260825080000_draft_reviews_foreign_key_index.sql
supabase/migrations/20260826080225_operator_auth_and_ownership.sql
supabase/migrations/20260826104022_evidence_resolution.sql
supabase/migrations/20260826110406_evidence_resolution_fk_indexes.sql
```

The first two were applied on 2026-08-23. The review and index migrations were
applied on 2026-08-25. The operator-authentication, evidence-resolution, and
foreign-key-index migrations were applied on 2026-08-26 after explicit approval.
Their remote versions are `20260826110215`, `20260826110253`, and
`20260826110442` respectively.
Before any future schema change, use the `supabase-proofshield` MCP
`get_project_url` tool and confirm the result is exactly:

```text
https://qoujhmqkjicvcwoiyqkp.supabase.co
```

Do not run ProofShield migrations through the older `supabase` connection.

The migrations create:

- ten RLS-enabled `proofshield_*` tables for operators, cases, evidence,
  evidence resolutions, response drafts, immutable human reviews, history,
  webhook state, and append-only audit entries;
- transaction-safe Postgres RPCs for case, draft, and webhook idempotency;
- indexes for every foreign key and primary read path;
- a private `proofshield-evidence` Storage bucket with a 5 MB limit and MIME
  allowlist;
- backend-only grants for `service_role`, with `anon` and `authenticated`
  access revoked.

The activation verification confirmed:

1. every `proofshield_*` table has RLS enabled;
2. the Storage bucket is private and enforces the 5 MB/MIME restrictions;
3. anonymous roles cannot read ProofShield tables and authenticated roles have
   only owner-scoped reads; browser mutation RPCs remain revoked;
4. service-role case, evidence, draft, history, and webhook transactions work;
5. replay and conflict results are deterministic;
6. the composite human-review and evidence-resolution foreign keys have covering
   indexes;
7. the no-write evidence-resolution probe returned `CASE_NOT_FOUND` without
   changing resolution or history counts;
8. the live Milestone 9 demo retained one intentionally labelled synthetic case,
   `demo_disp_m9_20260825`, for local dashboard demonstrations.

The advisor's `RLS Enabled No Policy` notices are intentional at this stage:
browser roles have no grants or policies, and only the trusted backend uses the
service role. `Unused Index` notices are expected for a new, nearly empty demo
database and are not recommendations to remove the required primary-read and
foreign-key indexes.

## Backend environment

Copy `.env.example` to `.env` and fill only local secret values:

```text
SUPABASE_PROJECT_REF=qoujhmqkjicvcwoiyqkp
SUPABASE_URL=https://qoujhmqkjicvcwoiyqkp.supabase.co
SUPABASE_SECRET_KEY=your_backend_secret_key
SUPABASE_EVIDENCE_BUCKET=proofshield-evidence
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
SUPABASE_PUBLISHABLE_KEY=your_browser_safe_publishable_key
```

Use `SUPABASE_SERVICE_ROLE_KEY` only for a legacy project that does not yet have
a modern secret key. ProofShield rejects publishable/anon keys for its backend
persistence. `SUPABASE_PUBLISHABLE_KEY` is intentionally browser-safe and is
returned by local FastAPI at `/v1/auth/config`; it is not a replacement for the
backend secret. Never commit `.env` and never prefix the secret with a frontend
environment convention such as `VITE_`, `NEXT_PUBLIC_`, or `PUBLIC_`.

## Named operator provisioning

Public signup is intentionally absent. Provision an operator in two explicit
steps:

1. create and confirm an email/password user in Supabase Authentication;
2. insert a matching active registry row using a trusted admin path:

```sql
insert into public.proofshield_operators (user_id, email, display_name)
values ('<auth-user-uuid>', '<normalized-email>', '<display name>');
```

The UUID and email must match `auth.users`. Passwords never belong in SQL or
Git. The local live-demo runner may receive operator email/password through
process-only `PROOFSHIELD_DEMO_OPERATOR_EMAIL` and
`PROOFSHIELD_DEMO_OPERATOR_PASSWORD` variables.

The preferred local workflow is the guarded onboarding runner, which also
requires `PROOFSHIELD_DEMO_OPERATOR_DISPLAY_NAME` and verifies the resulting
Supabase Auth session plus active registry identity:

```bash
PYTHONPATH=src python scripts/onboard_operator.py \
  --confirm-live-write \
  --project-ref qoujhmqkjicvcwoiyqkp
```

The command is safe to retry for the exact same active operator. It refuses a
wrong password, a conflicting email or display name, or an inactive registry
row. It never prints or stores the password.

## Deployment boundary

Supabase is the only cloud platform in the current architecture. The API and
frontend remain local. Hosting them later does not require changing the data
model; it requires securely adding the same backend environment variables to
the chosen server platform. The Supabase secret key must still remain
server-only.
