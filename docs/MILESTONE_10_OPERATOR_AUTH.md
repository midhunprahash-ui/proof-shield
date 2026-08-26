# Milestone 10: named operator authentication and case ownership

## Outcome

ProofShield now replaces the shared operator secret with named Supabase Auth
sessions. React signs in with a browser-safe publishable key, FastAPI verifies
the access token with Supabase Auth, and a server-controlled registry decides
whether the user is an active operator.

The API and React frontend remain local. Nothing is deployed, and ProofShield
still does not submit responses to Razorpay.

## Trust boundary

- The Supabase secret/service-role key remains backend-only.
- The browser receives only the project URL and publishable key.
- Public signup is absent; merchant administrators provision users.
- `user_metadata` is not used for authorization or reviewer identity.
- Every case endpoint requires a verified active operator.
- Cross-owner case reads return `404` to avoid confirming that another
  operator's case exists.
- The review request cannot contain a reviewer label. FastAPI stamps the
  verified Auth user ID and registry-controlled display name into the immutable
  review record.

## Webhook assignment flow

Razorpay webhooks have no human Supabase identity, so incoming cases begin with
`owner_id = null`. Active operators see only a minimal unassigned summary through
the trusted backend. Claiming calls one atomic Postgres RPC:

1. confirm the operator registry row is active;
2. update the case only when `owner_id is null`;
3. append `CASE_CLAIMED` to case history;
4. reject a competing claim without reassigning the case.

After the claim, only that owner can read or act on the full case workspace.
This Supabase project is currently one merchant boundary; organization-level
multi-tenancy can be added before onboarding multiple merchants.

## Database migration

`supabase/migrations/20260826080225_operator_auth_and_ownership.sql` adds:

- `proofshield_operators`, linked to `auth.users`;
- nullable case `owner_id` and immutable-review `reviewer_user_id` columns;
- indexes for owner queue reads and reviewer audit lookups;
- a private, pinned `SECURITY DEFINER` ownership helper;
- read-only, owner-scoped RLS policies for authenticated users;
- service-role-only save, list, claim, and review RPCs.

Authenticated users receive `SELECT` only. All browser writes and all public
RPC execution remain revoked.

## Risk summary

The remote project still records only the four Milestone 4-9 migrations. It has
one labelled synthetic demonstration case and zero Auth users. The Milestone 10
migration has not been applied because remote DDL requires explicit approval.
When applied, the existing case will remain safe and unassigned until a named
operator claims it; no synthetic or customer row is deleted.

## Why this is safer

The old shared secret could not prove which human acted and was available to any
person who knew the value. The new flow separates authentication from
authorization, derives audit identity from verified state, prevents silent case
reassignment, and keeps database writes behind the trusted backend.

## Validation completed

- Ruff: passed.
- Backend: `103 passed` with one existing Starlette/httpx deprecation warning.
- Frontend: TypeScript passed, `10` Bun tests passed, production bundle built.
- Auth regression tests cover missing, expired, inactive, and cross-owner access.
- Claim regression tests cover unassigned visibility, successful assignment,
  audit history, and a competing-operator race.
- Migration tests confirm pinned private helper security, ownership policies,
  required indexes, and service-role-only mutation RPCs.
- MCP OAuth was re-authenticated and the project URL was verified as
  `https://qoujhmqkjicvcwoiyqkp.supabase.co`.

## Activation and validation steps

1. explicitly approve the live schema change;
2. apply the migration through `supabase-proofshield`;
3. re-check tables, functions, grants, policies, and migration history;
4. run Supabase security and performance advisors;
5. create one confirmed Auth user and matching active operator row;
6. run authorized, unauthorized, cross-owner, and claim-race checks with real
   Supabase access tokens;
7. run the local React dashboard against the retained demo case.

If activation fails, keep the local API stopped and fix forward from the
migration error. Do not drop ownership or reviewer columns after they contain
audit data.
