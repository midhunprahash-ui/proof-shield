# Supabase setup for ProofShield

## Project boundary

ProofShield uses Supabase project `qoujhmqkjicvcwoiyqkp`.

The Codex connection is named `supabase-proofshield` because this computer
already had a `supabase` MCP connection for a different project. Keeping both
names prevents an accidental schema change in the unrelated project.

The configured command is:

```bash
codex mcp add supabase-proofshield --url 'https://mcp.supabase.com/mcp?project_ref=qoujhmqkjicvcwoiyqkp&features=docs%2Caccount%2Cdatabase%2Cdebugging%2Cdevelopment%2Cfunctions%2Cbranching'
codex mcp login supabase-proofshield
```

Run `/mcp` in a new Codex task and confirm `supabase-proofshield` is enabled.
MCP servers added during an existing task load on the next task/session.

## Apply the repository migration

The source-of-truth migration is:

```text
supabase/migrations/20260822190000_proofshield_supabase_foundation.sql
```

Before applying it, use the `supabase-proofshield` MCP `get_project_url` tool
and confirm the result is exactly:

```text
https://qoujhmqkjicvcwoiyqkp.supabase.co
```

Then apply the migration to that project. Do not run it through the older
`supabase` connection.

The migration creates:

- six RLS-enabled `proofshield_*` tables for cases, evidence, history, webhook
  state, and append-only audit entries;
- transaction-safe Postgres RPCs for case idempotency and webhook claims;
- indexes for every foreign key and primary read path;
- a private `proofshield-evidence` Storage bucket with a 5 MB limit and MIME
  allowlist;
- backend-only grants for `service_role`, with `anon` and `authenticated`
  access revoked.

After applying it:

1. list the `public` tables and confirm every `proofshield_*` table has RLS;
2. confirm the Storage bucket is private;
3. run Supabase security and performance advisors;
4. execute a transaction-safe test case through `proofshield_save_case`, read
   it back, and remove the synthetic verification row before real use.

## Backend environment

Copy `.env.example` to `.env` and fill only local secret values:

```text
SUPABASE_PROJECT_REF=qoujhmqkjicvcwoiyqkp
SUPABASE_URL=https://qoujhmqkjicvcwoiyqkp.supabase.co
SUPABASE_SECRET_KEY=your_backend_secret_key
SUPABASE_EVIDENCE_BUCKET=proofshield-evidence
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
```

Use `SUPABASE_SERVICE_ROLE_KEY` only for a legacy project that does not yet have
a modern secret key. ProofShield rejects publishable/anon keys for its backend
persistence. Never commit `.env` and never prefix the secret with a frontend
environment convention such as `VITE_`, `NEXT_PUBLIC_`, or `PUBLIC_`.

## Deployment boundary

Supabase is the only cloud platform in the current architecture. The API and
frontend remain local. Hosting them later does not require changing the data
model; it requires securely adding the same backend environment variables to
the chosen server platform. The Supabase secret key must still remain
server-only.
