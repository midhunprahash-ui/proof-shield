# Milestone 16: live operator onboarding and end-to-end demo

## Outcome

ProofShield now has a guarded command for provisioning the first named operator
in live Supabase. The command creates or reuses the exact Auth identity, proves
the supplied password can start a session, adds the matching active operator
registry row, and verifies the backend operator gate.

No model training is part of this milestone. The product advantage remains the
traceable workflow: source evidence, deterministic consistency checks, explicit
human approval, and a tamper-evident response packet.

## Security boundary

- The Supabase secret key stays in the local backend environment.
- The operator password is read only from
  `PROOFSHIELD_DEMO_OPERATOR_PASSWORD`; it is not accepted as a CLI argument.
- The command prints no password or access token.
- Authorization uses the server-controlled `proofshield_operators` registry,
  not user-editable Auth metadata.
- Existing inactive operators are not silently reactivated.
- A wrong project reference, conflicting identity, or failed sign-in stops the
  operation.

## Provision the first operator

Put these values in the local ignored `.env` or export them only for the current
shell:

```text
PROOFSHIELD_DEMO_OPERATOR_EMAIL=<operator email>
PROOFSHIELD_DEMO_OPERATOR_PASSWORD=<strong password, at least 12 characters>
PROOFSHIELD_DEMO_OPERATOR_DISPLAY_NAME=<name shown in audit records>
```

Then explicitly acknowledge the live write:

```bash
PYTHONPATH=src python scripts/onboard_operator.py \
  --confirm-live-write \
  --project-ref qoujhmqkjicvcwoiyqkp
```

The result reports whether the Auth user and registry row were created or were
already present. It also reports that sign-in and operator access were verified.

## End-to-end demonstration

After onboarding, run the retained synthetic demo:

```bash
PYTHONPATH=src python scripts/run_live_demo.py \
  --confirm-live-write \
  --project-ref qoujhmqkjicvcwoiyqkp \
  --label milestone_16
```

The complete judge-facing flow is:

1. sign in as the named Supabase operator;
2. claim the existing unassigned webhook case in the React queue;
3. upload or inspect invoice and delivery evidence;
4. run extraction and review every proposed value;
5. assess deterministic cross-source consistency;
6. resolve incorrect or superseded evidence without deleting history;
7. create a cited response draft;
8. approve the immutable draft as the verified operator;
9. download the deterministic packet and verify its hashes;
10. show the append-only audit timeline and matching Supabase records.

## Verification

Automated tests cover new-user onboarding, safe retry, wrong-password refusal,
and inactive-operator refusal. The full backend and React checks must pass on the
feature branch before this milestone reaches `develop`.

The live run remains intentionally blocked until the operator supplies their own
email, strong password and display name in the ignored local environment. This
prevents generated or transcript-visible credentials from becoming a live
account.
