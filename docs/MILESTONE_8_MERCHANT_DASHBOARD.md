# Milestone 8: React merchant dashboard

## Outcome

ProofShield now has a local merchant operations interface for the complete
human-controlled chargeback workflow. The frontend uses React 19, TypeScript,
and Bun's native HTML bundler. It is not deployed.

An operator can:

- see queue volume and evidence readiness at a glance;
- search the dispute queue by dispute, order, or payment ID;
- inspect immutable case and payment facts;
- upload a private evidence source and record human-reviewed facts;
- run the deterministic assessment and see each exact check;
- create an evidence-grounded draft only when the backend allows it;
- inspect every draft claim and source-file hash;
- approve or reject the draft once through the protected operator gate;
- download the tamper-evident packet only after approval; and
- read the append-only case timeline.

There is still no automatic or manual Razorpay submission button. Approval only
unlocks the evidence packet.

## Browser-to-cloud boundary

The frontend calls FastAPI and nothing else. It does not import the Supabase
client, use a browser-facing Supabase key, or access Postgres and Storage
directly. It also has no analytics, hosted font, or other cloud dependency.
Supabase remains the only managed cloud system.

The local API permits CORS only from the configured development origins:

```text
http://localhost:3000
http://127.0.0.1:3000
```

Override them with `PROOFSHIELD_CORS_ORIGINS`. Browser CORS permits only the
methods and headers used by this console. Credentials mode stays disabled.

## Temporary operator control

Review and packet endpoints still require `X-ProofShield-Operator-Secret`.
The console asks for this value only when protected controls are needed, keeps
it in React state, and clears it on page close or when the operator clicks
clear. It is not written to local or session storage and is not bundled.

This is acceptable only for the current local milestone. Supabase Auth, named
operator identities, case ownership, and narrow RLS policies are required before
the frontend or API is deployed.

## Run locally

Start the configured Supabase-backed API:

```bash
source .venv/bin/activate
uvicorn proofshield.api:app --reload
```

Start the Bun development server separately:

```bash
cd frontend
bun install --frozen-lockfile
bun run dev
```

Open `http://localhost:3000`.

The API URL defaults to `http://127.0.0.1:8000` through the
`proofshield-api-url` meta tag in `frontend/index.html`. This is public runtime
configuration, so it must never contain a secret.

## Build and test

```bash
cd frontend
bun run check
```

`check` runs strict TypeScript validation, Bun tests, and the minified HTML
bundle. Milestone verification completed with:

- 8 frontend tests passing;
- strict TypeScript validation passing;
- a 23-module production bundle completing successfully;
- backend Ruff validation passing;
- 91 backend tests passing;
- a real local browser connection to the configured Supabase-backed API;
- desktop and 390-pixel responsive layout inspection;
- accessible names on compact mobile navigation;
- keyboard-focused operator dialog behavior; and
- no browser console warnings or errors after the integration fix.

The connected live Supabase project returned successful empty-queue responses
during this verification, and the browser recovered through its explicit error
state and retry path. The same session also observed intermittent upstream
`JWT issued at future` and HTTP/2 disconnect errors, so uninterrupted live
Supabase stability is not yet claimed. No synthetic rows were added to the live
project merely for a UI screenshot. Backend contract tests continue to cover
evidence, drafting, review, authorization, immutability, and packet generation.

## Known boundary

Milestone 7's draft-review migration still needs live MCP activation and live
Supabase verification. The dashboard code and API contract are ready for it,
but protected review actions should not be called against the live project
until that migration is confirmed. This does not block local frontend build,
type, API-contract, or browser verification.

## Next milestone

Activate and verify the Milestone 7 review migration, then seed a clearly
labelled demonstration case through the trusted backend and run a recorded
end-to-end merchant workflow. Recheck machine/Supabase clock agreement and the
HTTP transport if the transient live errors recur. Authentication and
deployment remain later, separate decisions.
