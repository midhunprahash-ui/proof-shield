# Milestone 1: trustworthy decision foundation

## What works now

ProofShield can accept a structured product-not-received dispute and check:

1. Whether the dispute type is supported.
2. Whether the response deadline is still open.
3. Whether the payment is captured.
4. Whether the payment ID, order ID, amount, and currency agree.
5. Whether a verified invoice exists and matches the dispute.
6. Whether verified delivery proof exists, matches the order, and says delivered.
7. Whether optional customer communication acknowledges delivery.

The API returns every check rather than only a final label. This makes the
decision explainable and gives the future operator dashboard an honest audit
trail.

## Why there is no trained model yet

A trained model would need credible labels for the exact decision we want to
make: whether a dispute has enough consistent evidence to safely prepare a
contest response. Training on labels created by the same rules used to evaluate
the model would be circular and misleading.

Milestone 1 therefore establishes a transparent baseline. Later we will compare:

- deterministic rules only;
- AI extraction/recommendation only;
- the ProofShield hybrid system.

A learned decision model will be added only if independently reviewed data is
large enough and the model improves held-out precision, recall, and false-positive
cost over this baseline.

## Synthetic data warning

`proofshield-generate` creates reproducible development fixtures covering known
scenarios. It is useful for engineering and regression testing, but it is not
independent evidence of real-world model performance.

Before reporting Buildathon metrics, we will:

1. Add more document and merchant templates.
2. Separate development and test data by template family.
3. Freeze the test set before tuning decisions.
4. Have a human review the expected decisions.
5. Publish the confusion matrix and false-positive examples.

## Known limitations

- Only product-not-received disputes are supported.
- Inputs are structured JSON; PDF/email extraction is not implemented yet.
- Razorpay webhook signature verification and event idempotency come next.
- No LLM is connected yet.
- No response is submitted automatically.
- The evidence score is check coverage, not a calibrated probability.

## Next milestone

Add a safe webhook ingestion layer using raw-body signature verification,
duplicate-event protection, an official-payload-compatible adapter, and stored
audit events. Then add document extraction behind the verifier.
