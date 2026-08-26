# Milestone 11: safe evidence extraction baseline

## Outcome

ProofShield can now read exact labelled fields from uploaded JSON and UTF-8 text
sources and return a typed extraction proposal. Each proposed fact includes:

- a supported field name;
- a normalized string or boolean value;
- a score bounded from zero to one;
- an exact JSON pointer or text line reference.

The proposal is not evidence. It cannot set `source_verified`, cannot bypass the
existing deterministic verifier, and cannot create a database record until a
human reviews the editable form and checks the confirmation control.

No model was trained for this milestone. This deterministic baseline gives
future OCR or document-model providers a stable contract and a measurable score
to beat.

## Supported local sources

The baseline supports:

- `application/json` objects with exact labelled scalar fields;
- `text/plain` files containing `Label: value` lines.

It extracts only fields allowed for the chosen evidence type. Unknown keys,
nested JSON, duplicate fields, and fields belonging to another evidence type
are ignored. Amounts are normalized without floating-point conversion.

PDF, PNG, and JPEG extraction returns HTTP `415` with an honest provider-required
message. Uploading those formats is still supported for manual review and packet
generation; the system simply refuses to pretend it can read them locally.

## Protected API flow

```text
POST /v1/cases/{dispute_id}/files/{file_id}/extract
  -> verify active operator bearer token
  -> require case ownership
  -> resolve the registered private-storage object
  -> read source bytes through the backend
  -> verify bytes against the registered SHA-256
  -> return an unverified proposal
  -> operator reviews/edits the existing evidence form
  -> explicit confirmation uses the existing append-only evidence endpoint
```

Cross-owner requests remain indistinguishable from missing cases. The browser
never receives the Supabase secret key or a private Storage credential.

## Frozen evaluation set

`data/synthetic/extraction_cases.jsonl` contains six clearly synthetic cases
covering invoices, delivery proofs, and customer communications across JSON and
text sources. The evaluation CLI reports field precision, field recall, exact
case accuracy, and field-level error examples:

```bash
PYTHONPATH=src python -m proofshield.extraction_evaluation \
  --input data/synthetic/extraction_cases.jsonl
```

The deterministic baseline currently produces:

- 6 cases;
- 18 expected and proposed fields;
- field precision `1.0`;
- field recall `1.0`;
- exact case accuracy `1.0`.

These results apply only to the frozen labelled-field fixtures. They are not a
claim about messy real invoices, scans, handwriting, or OCR quality.

## Verification

- Unit tests cover JSON pointers, text line references, amount and boolean
  normalization, missing-field warnings, unsupported formats, and SHA-256
  mismatch refusal.
- API tests cover owned source extraction and honest PDF refusal.
- Frontend tests cover the extraction request and ensure no verified flag is
  returned.
- The React workspace keeps all proposed values editable and clears human
  confirmation whenever the source, type, or proposal changes.

## Next milestone

Add one configurable OCR/document provider for PDF and image sources, run it on
a separate synthetic scan set, compare it against this baseline, and persist
proposal/review outcomes only after the data model is reviewed. A provider's
score must never become a verification decision by itself.

The local-provider portion is now implemented in
`MILESTONE_12_LOCAL_OCR.md`. Proposal persistence remains intentionally deferred
until its audit and retention model is designed.
