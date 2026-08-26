# Milestone 15: append-only evidence resolution

## Outcome

ProofShield now gives an authenticated case owner a controlled way to stop an
incorrect evidence record from influencing future checks without changing or
deleting the original record.

An operator can record one of two permanent actions:

- `EXCLUDED_INCORRECT`: the evidence was attached or recorded incorrectly and
  has no replacement;
- `SUPERSEDED`: a newer evidence record of the same type replaces it.

Every resolution requires a reason and the verified operator identity. One
evidence record can have only one immutable resolution. Exact retries are
idempotent; a different second action is rejected.

## Simple flow

```text
append-only evidence records
       |
       v
operator finds an incorrect or outdated record
       |
       v
explicit action + reason + permanent-action confirmation
       |
       v
separate immutable resolution row + EVIDENCE_RESOLVED history event
       |
       v
analyzer and verifier use only active evidence
       |
       v
old drafts become stale; reassessment and a new approval are required
```

The evidence row, private source file, hash, and prior history remain untouched.
The UI continues to show the record with a resolved label so the correction is
auditable rather than hidden.

## Safety rules

- A mandatory reason must contain 10 to 2,000 trimmed characters.
- `SUPERSEDED` requires a replacement in the same case and with the same
  evidence type.
- A resolved record cannot be used as a replacement.
- A replacement record cannot later be resolved, preventing ambiguous chains.
- The database locks source and replacement rows while validating the action so
  competing resolutions fail safely.
- Browser roles receive owner-scoped `SELECT` only. The mutation RPC remains
  service-role-only and uses a pinned empty search path.
- Original evidence and source files receive no update or delete operation.

## Analyzer, drafts and packets

The consistency report now names:

- `resolution_count`;
- `excluded_evidence_ids`;
- `active_evidence_ids`.

The verifier runs invoice, delivery, customer-communication and cross-source
checks against the active set. Excluding the only required invoice or delivery
proof therefore makes the case incomplete; a resolution cannot manufacture a
safe decision.

Draft fingerprints include the complete consistency report. Any resolution
invalidates a draft created before the action. Approval and packet export both
recompute the active set and reject stale drafts.

Evidence packets are now `proofshield-evidence-packet-v3`. They contain
`evidence-resolutions.json`, and the manifest seals its canonical SHA-256 plus
the resolution count. Resolved evidence cannot appear as a citation in a new
draft.

## API and operator console

New protected endpoints:

- `GET /v1/cases/{dispute_id}/resolutions`;
- `POST /v1/cases/{dispute_id}/resolutions`.

The browser cannot supply `resolved_by`; FastAPI derives it from the verified
Supabase Auth operator. The Evidence tab requires a target, action, reason and
explicit confirmation before enabling the permanent action.

## Database migration

`supabase/migrations/20260826104022_evidence_resolution.sql` adds:

- the append-only `proofshield_evidence_resolutions` table;
- same-case source and replacement foreign keys;
- owner-scoped read RLS and explicit grants;
- lookup, replacement and resolver indexes;
- the service-only `proofshield_resolve_evidence` RPC;
- the `EVIDENCE_RESOLVED` history action.

`supabase/migrations/20260826110406_evidence_resolution_fk_indexes.sql` adds
covering indexes for both composite source/replacement foreign keys after the
Supabase performance advisor identified them.

### Risk summary

The migrations are additive and do not rewrite existing evidence. Activation
followed the required order because evidence resolutions depend on the operator
registry, ownership columns, private ownership helper, and policies.

### Completed activation order

1. explicit live-project approval was received;
2. `20260826080225_operator_auth_and_ownership.sql` was applied;
3. `20260826104022_evidence_resolution.sql` was applied;
4. RLS, grants, policies, function privileges and indexes were verified;
5. a no-write `CASE_NOT_FOUND` RPC probe preserved resolution/history counts;
6. the advisor-driven composite foreign-key indexes were applied;
7. security and performance advisors were rerun.

If either migration fails, stop local API use and fix forward. Do not drop
ownership, reviewer or resolution records after they contain audit data.

## Current remote status

Live project `qoujhmqkjicvcwoiyqkp` records:

- `20260826110215 operator_auth_and_ownership`;
- `20260826110253 evidence_resolution`;
- `20260826110442 evidence_resolution_fk_indexes`.

`proofshield_operators` and `proofshield_evidence_resolutions` both have RLS
enabled. Authenticated users have owner-scoped `SELECT` only; they cannot insert
resolution rows or execute the resolution RPC. The service role can insert and
execute the RPC. Existing counts remained one case, two evidence rows, one
review, eight history entries, and zero resolutions.

The security advisor now reports only the two intentional no-policy notices for
backend-only webhook tables. The missing-foreign-key-index notices are cleared.
Unused-index notices are expected while the live dataset remains nearly empty.

## Verification coverage

Automated tests cover:

- excluding a conflicting record restores consistency;
- excluding the only required record makes the case incomplete;
- same-type replacement enforcement;
- immutable and idempotent resolution behavior;
- original evidence retention and one history event;
- authenticated API creation, listing and retry behavior;
- stale draft rejection after a resolution;
- new drafts citing only active evidence;
- packet version 3 resolution audit contents;
- RLS, grants, indexes, constraints and browser RPC revocation;
- six parallel React workspace reads and caller-controlled identity exclusion.

No model training, LLM call or cloud OCR service is involved in this workflow.
