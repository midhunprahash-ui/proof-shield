# Milestone 14: consistency-aware drafting and packet freshness

## Outcome

ProofShield now refuses to draft from an evidence set when a later record
conflicts with an earlier invoice or delivery proof. It also blocks drafting when
any recorded source is unverified or a required fact is missing.

The cross-source report still does not decide whether the merchant should contest
the chargeback. It provides deterministic facts to the existing draft-readiness
policy. Final response approval remains an authenticated human action, and no
response is submitted automatically.

## The safety gap this closes

The earlier verifier checked the first invoice and first delivery record. The
Milestone 13 report displayed later conflicts, but it was possible for the first
records to remain individually valid while a second record disagreed.

Milestone 14 makes the complete append-only evidence set part of draft readiness:

```text
current case and every evidence record
  -> derived consistency report
  -> deterministic assessment check
  -> CONSISTENT: drafting may continue
  -> conflict, missing required fact, or unverified source: drafting stops
  -> human resolves the evidence and runs a new assessment
```

The new checks are:

- `CROSS_SOURCE_CONSISTENT`;
- `CROSS_SOURCE_CONFLICT`;
- `CROSS_SOURCE_INCOMPLETE`;
- `CROSS_SOURCE_UNVERIFIED`.

These checks affect only `SAFE_TO_DRAFT`, `NEEDS_REVIEW`, or
`INSUFFICIENT_EVIDENCE`. They do not approve, reject, or submit a chargeback.

## Stale approval protection

A draft input fingerprint already covered the complete case, evidence, and
assessment checks. Packet export now recomputes that fingerprint from the current
case.

Approval and packet export both recompute the current state. If any evidence is
attached after the draft was created:

- conflicting evidence blocks export because the current report is not
  consistent;
- even matching evidence changes the fingerprint and blocks the old packet;
- the operator must reassess, create a new draft, and approve that new draft.

This prevents an approval from silently applying to evidence the reviewer had not
seen.

Drafts created before this milestone do not contain the new cross-source
assessment check in their input fingerprint. They intentionally fail the current
fingerprint comparison and must be recreated and approved again; no stored draft
or review is mutated.

## Evidence packet version 2

Approved packet export re-checks ownership, current consistency, current draft
fingerprint, cited file provenance, file size, and SHA-256 before creating the
archive.

The packet now contains `consistency-report.json`. The manifest contains:

- `format: proofshield-evidence-packet-v2`;
- `consistency_status`;
- `consistency_report_sha256`.

The report file uses deterministic canonical JSON, and its SHA-256 is covered by
the manifest hash. Repeated export of unchanged approved state remains
byte-for-byte stable.

## Supabase and cloud boundary

No schema or policy changed. The API reads the current immutable evidence JSON
through the existing ownership-protected Supabase repository and reads only the
cited private Storage objects when export is allowed. The consistency report is
derived in memory and is written only inside the downloaded packet.

No browser receives the backend Supabase secret, Storage path, or raw private
object credential.

## Verification coverage

Tests cover:

- a later conflicting invoice changing a formerly safe case to `NEEDS_REVIEW`;
- a later matching but unverified source blocking drafting;
- evidence changes altering the draft input fingerprint;
- conflicting post-approval evidence blocking packet export and new drafting;
- matching post-approval evidence invalidating the old approval;
- pre-approval evidence changes preventing a stale approval from being recorded;
- packet version 2 contents and the consistency-report SHA-256;
- unchanged packet determinism and existing file-tamper refusal.

Final verification passed 138 backend tests, 11 frontend tests, Python linting,
TypeScript checking, and the Bun production bundle. A live read-only Supabase
query confirmed every current evidence row stores `document_json` as a JSON
object; no remote data or schema was changed.

## Next step completed

[Milestone 15](MILESTONE_15_EVIDENCE_RESOLUTION.md) adds the explicit operator
resolution workflow while preserving the append-only source history.
