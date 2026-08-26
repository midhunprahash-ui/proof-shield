# Milestone 12: local OCR with a replaceable provider boundary

## Outcome

ProofShield can now read PDF, PNG, and JPEG evidence through a local PP-OCRv6
provider. The backend converts OCR text into the same typed, editable proposals
already used for JSON and UTF-8 text. Each proposed field carries:

- the normalized value;
- the provider confidence score;
- a page number and pixel bounding box;
- the registered source file ID and SHA-256 hash.

OCR output is never evidence by itself. It cannot set `source_verified`, cannot
write a structured evidence record, and cannot bypass the deterministic case
verifier. An operator must still inspect the source, edit any value, and check
the explicit confirmation control before an append-only evidence record is
created.

No model was trained. ProofShield uses the published PP-OCRv6 weights locally.

## Why local first

Local inference keeps Supabase as the only managed cloud dependency. Evidence
bytes are downloaded from the private Storage bucket by FastAPI, checked against
their registered SHA-256, written to a short-lived private temporary directory,
processed locally, and deleted immediately afterward.

The first PP-OCRv6 initialization downloads model weights from PaddleOCR's model
host into the machine's PaddleX model cache. After setup, document inference is
local and does not require an OCR API key. The model cache is not committed.

## Replaceable provider design

`DocumentOcrProvider` is the stable backend contract. A provider accepts trusted
source bytes and a content type and returns `OcrTextObservation` records. Every
observation must contain text, confidence, page number, and a positive-area
bounding box.

`RoutingEvidenceExtractor` keeps provider choice outside the API contract:

```text
JSON / UTF-8 text
  -> deterministic labelled-field extractor

PDF / PNG / JPEG
  -> configured DocumentOcrProvider
  -> located OCR observations
  -> conservative labelled-field normalizer

both routes
  -> identical unverified EvidenceExtractionProposal
  -> editable React review form
  -> explicit human confirmation
  -> append-only structured evidence
```

The current factory recognizes `paddle` and `disabled`. A future Azure, Google,
Mistral, or other cloud adapter can implement `DocumentOcrProvider`; the endpoint,
frontend, SHA-256 check, proposal schema, and human-review boundary remain the
same. Cloud credentials must remain backend-only when such an adapter is added.

## Local configuration

Install the OCR extra in the existing Python environment:

```bash
python -m pip install -e '.[dev,ocr]'
```

The pinned local runtime is:

- `paddleocr==3.7.0`;
- `paddlepaddle==3.2.1`;
- `Pillow==12.3.0`;
- PP-OCRv6 medium detection and recognition models selected by PaddleOCR 3.7.

Environment controls:

```text
PROOFSHIELD_OCR_PROVIDER=paddle
PROOFSHIELD_OCR_MIN_CONFIDENCE=0.5
PROOFSHIELD_OCR_MAX_PAGES=10
```

Set the provider to `disabled` to keep JSON/text extraction available while
returning an honest `415` for PDF/image extraction. An unavailable PaddleOCR
runtime returns `503`. Invalid provider output, SHA-256 mismatch, or unsafe
processing failure returns a closed error rather than a partial proposal.

Inference is serialized inside one API process because the local pipeline is
shared and should not be assumed thread-safe. The existing 5 MB evidence upload
limit remains in force, and OCR adds a default 10-page limit.

## Frozen synthetic scan benchmark

The generator creates three clearly labelled documents with no merchant or
customer data:

```bash
python scripts/generate_synthetic_ocr_fixtures.py
python -m proofshield.ocr_evaluation \
  --input data/synthetic/ocr/ocr_cases.jsonl
```

The Apple Silicon local run completed with:

- 3 synthetic scan cases;
- 11 expected and proposed fields;
- 11 correct fields;
- field precision `1.0`;
- field recall `1.0`;
- exact-case accuracy `1.0`.

This result proves the local adapter, model runtime, location mapping, field
normalization, and evaluation path on clean generated documents. It is not a
claim about arbitrary merchant invoices, handwriting, blurred photographs,
regional templates, or production accuracy. Provider selection must eventually
use a separately reviewed, varied holdout set.

## Security and failure behavior

- Case ownership is checked before private source bytes are read.
- Registered bytes must pass a fresh SHA-256 check before OCR.
- Temporary files use a private generated directory and are deleted afterward.
- Provider observations below the configured confidence floor are discarded.
- Low-confidence proposed fields produce an explicit warning.
- A page and bounding box are retained so the operator can inspect the source.
- Provider scores never become verification or approval decisions.
- The browser receives no Supabase secret, Storage credential, or future OCR key.
- OCR proposals are not persisted in this milestone.

## Verification coverage

Tests cover provider result parsing, temporary-file cleanup, page limits,
malformed provider output, confidence filtering, source-location preservation,
SHA-256-before-provider ordering, API success and unavailable-provider errors,
manifest path traversal, configuration switching, and the unchanged
human-confirmation boundary. The final milestone verification passed 124 backend
tests, 11 frontend tests, frontend type-checking, and the production bundle.

## Next milestone

Milestone 13 should compare document facts across sources, surface conflicts and
missing evidence to the operator, and remain advisory. It must not convert model
or OCR confidence into an automatic chargeback decision.
