# Milestone 13: advisory cross-source evidence consistency

## Outcome

ProofShield now compares every confirmed evidence record attached to a case. The
operator sees which required source types are present, whether their sources were
human verified, which facts agree, which facts are missing, and exactly which
records disagree.

This is an advisory report. It does not approve a chargeback response, change the
case assessment, persist a new decision, or turn OCR confidence into truth. Human
review remains mandatory.

## What is compared

The analyzer checks all recorded values instead of trusting only the first record:

- order ID across invoices, delivery proofs, and customer communications;
- payment ID across every source that supplies it;
- invoice amount against the disputed amount;
- delivery status against the expected delivered state;
- customer delivery acknowledgement across supplied customer communications.

Invoice and delivery-proof coverage is required. Customer communication remains
optional. Missing optional communication does not make an otherwise complete
report fail.

Every observation returned to the frontend retains its evidence ID, evidence
type, source name, source-verification state, value, and whether it matches the
trusted case fact. The report never returns private Storage paths or credentials.

## Report states

The report uses clear precedence so the most urgent issue is visible:

1. `CONFLICTS_FOUND`: at least one recorded value disagrees with the case or
   another source;
2. `INCOMPLETE`: a required source or required fact is missing;
3. `UNVERIFIED_SOURCES`: values agree, but at least one source was not human
   verified;
4. `CONSISTENT`: required sources are present, verified, and their values agree.

Counts for conflicts, missing checks, and unverified source records are returned
separately, so a conflict does not hide an additional missing-field warning.

## Protected API flow

```text
GET /v1/cases/{dispute_id}/consistency
  -> verify the Supabase bearer token
  -> require active operator access and exact case ownership
  -> load immutable case and evidence JSON through the backend repository
  -> compare all sources deterministically in memory
  -> return an advisory, human-review-required report
```

Cross-owner access continues to look like a missing case. The browser receives
neither the Supabase secret key nor a private Storage credential.

## Why there is no migration

The existing `proofshield_evidence.document_json` records already contain the
confirmed values, evidence type, provenance, and source-verification state needed
for comparison. The report is calculated on demand and is intentionally not
persisted. No table, RLS policy, database function, or Storage policy changed in
this milestone.

Keeping the report derived prevents stale consistency results when a new
append-only evidence record is attached. The next workspace refresh recomputes
the report from the complete evidence set.

## Operator interface

The Evidence tab now shows:

- one overall source-consistency status;
- required and optional source coverage;
- conflict, missing, and unverified counts;
- each expected fact and every source value;
- the exact evidence IDs missing a required field;
- an explicit reminder that the result is advisory.

The workspace loads the case, consistency report, files, drafts, and history in
parallel. Adding evidence and refreshing the workspace immediately updates the
derived report.

## Verification coverage

Tests cover:

- complete matching evidence;
- optional customer communication;
- missing delivery evidence and required facts;
- a later conflicting invoice that must not be hidden by the first invoice;
- matching facts from an unverified source;
- conflicting optional customer acknowledgements;
- authenticated API access and the advisory-only response contract;
- parallel frontend workspace loading.

Final verification passed 132 backend tests, 11 frontend tests, Python linting,
TypeScript checking, and the Bun production bundle. A read-only query against the
configured Supabase project confirmed that the evidence table and its structured
`document_json` records are available; no remote data was changed.

## Limitations and next step

This milestone compares only the structured fields already reviewed into an
evidence record. It does not compare free-form message meaning, carrier API data,
image similarity, handwriting, or timestamps beyond the existing typed facts.

A future milestone can decide how deterministic consistency findings should
participate in the drafting gate and evidence packet. That change must be tested
as a separate policy decision and must still require final human approval.

That policy hardening is now implemented separately in
`MILESTONE_14_CONSISTENCY_GATE.md`. The report still never decides the chargeback;
Milestone 14 uses only deterministic report states to protect drafting and packet
export.
