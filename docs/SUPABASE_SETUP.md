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

## Applied repository migration

The source-of-truth migration is:

```text
supabase/migrations/20260823160507_proofshield_supabase_foundation.sql
```

It was applied on 2026-08-23 and is recorded by Supabase as migration version
`20260823160507`. Before any future schema change, use the
`supabase-proofshield` MCP `get_project_url` tool and confirm the result is exactly:

```text
https://qoujhmqkjicvcwoiyqkp.supabase.co
```

Do not run ProofShield migrations through the older `supabase` connection.

The migration creates:

- six RLS-enabled `proofshield_*` tables for cases, evidence, history, webhook
  state, and append-only audit entries;
- transaction-safe Postgres RPCs for case idempotency and webhook claims;
- indexes for every foreign key and primary read path;
- a private `proofshield-evidence` Storage bucket with a 5 MB limit and MIME
  allowlist;
- backend-only grants for `service_role`, with `anon` and `authenticated`
  access revoked.

The activation verification confirmed:

1. every `proofshield_*` table has RLS enabled;
2. the Storage bucket is private and enforces the 5 MB/MIME restrictions;
3. anonymous and authenticated roles cannot access tables or RPCs;
4. service-role case, evidence, history, and webhook transactions work;
5. replay and conflict results are deterministic;
6. all synthetic verification data was removed after the test.

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
