# Milestone 3: trusted local case and evidence store

## What works now

ProofShield can complete this local workflow:

```text
Receive or create dispute
-> store case in SQLite
-> upload evidence source
-> manually confirm structured facts
-> link evidence to the case
-> reassess the case
-> inspect the complete history
```

No deployment, cloud database, or external storage is used.

## Local case database

The SQLite database defaults to:

```text
data/runtime/proofshield.sqlite3
```

It stores:

- immutable dispute, payment, and order facts;
- evidence-file metadata;
- structured evidence records;
- append-only case history.

If the same dispute ID arrives again with identical core facts, the repository
treats it as an idempotent replay. If its payment, order, amount, or other core
facts differ, ProofShield rejects the conflict instead of overwriting the case.

## Evidence source files

Local files are accepted through:

```text
POST /v1/cases/{dispute_id}/files
```

Current controls:

- 5 MB maximum;
- allowed types: PDF, PNG, JPEG, JSON, and UTF-8 text;
- path components are removed from the supplied filename;
- PDF/image magic bytes are checked;
- JSON must parse and text must be valid UTF-8;
- content is stored using its SHA-256 digest, not the supplied filename;
- the database exposes no filesystem path;
- runtime evidence is ignored by Git.

The file record receives a server-generated `file_id`. A file belonging to one
case cannot be referenced as evidence by another case.

## Manual structured evidence

Uploading a document does not prove what it says. A person must review it and
submit structured facts through:

```text
POST /v1/cases/{dispute_id}/evidence
```

For example, an invoice record may include the order ID, payment ID, amount,
and whether the reviewer confirms the source. A delivery record may include the
order ID and delivery status.

The server copies the uploaded file's real name and SHA-256 digest into the
evidence record. The caller cannot invent a different hash for a stored file.

Manual entries without a file are still allowed for development, but they have
no source digest. The final demo should prefer uploaded synthetic sources.

## Evidence isolation

ProofShield uses two independent protections:

1. SQLite foreign keys bind files and evidence to a dispute case.
2. The verifier checks the document's order ID, payment ID, amount, source
   confirmation, and delivery status.

A mismatched document remains visible in the audit trail but produces
`NEEDS_REVIEW`; it cannot silently help a case become `SAFE_TO_DRAFT`.

## Case history

The history endpoint records:

- `CASE_CREATED`
- `FILE_UPLOADED`
- `EVIDENCE_ADDED`
- `ASSESSED`

History entries are append-only and ordered. They intentionally avoid storing
raw document text in the event description.

## Honest limitations

- File types are validated but no malware scanner is included in this local demo.
- Uploaded files are not rendered or executed.
- Document facts are entered manually; AI extraction is not implemented yet.
- The SQLite repository is designed for one local application, not distributed use.
- Runtime data is local and has no automated backup.
- No trained model is used.

## Why this milestone comes before AI

The future AI reader needs original source files and trustworthy labels. This
milestone gives us both: preserved source bytes plus human-confirmed facts. We
can later measure whether AI extracts those facts correctly instead of judging
it by convincing-looking prose.

## Next milestone

Generate a small, clearly synthetic evidence pack for several dispute cases,
then add provider-independent AI extraction that:

1. reads one source;
2. returns typed claims with confidence and source references;
3. never marks its own output as verified;
4. falls back to manual entry;
5. is measured against the human-confirmed facts stored here.
