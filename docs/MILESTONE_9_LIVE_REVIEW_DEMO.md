# Milestone 9: live review and evidence-packet demo

## Outcome

The human-review schema is active on the intended ProofShield Supabase project,
and one clearly labelled synthetic case completed the entire trusted-backend
workflow. The API and React frontend remain local; nothing was deployed.

## Remote schema activation

The authenticated `supabase-proofshield` connection returned exactly:

```text
https://qoujhmqkjicvcwoiyqkp.supabase.co
```

Supabase records these remote migrations:

```text
20260825073901  draft_reviews_and_evidence_packets
20260825074158  draft_reviews_foreign_key_index
```

Post-activation inspection confirmed:

- `proofshield_draft_reviews` exists with RLS enabled;
- `anon` and `authenticated` cannot select, insert, or execute the review RPC;
- `service_role` can select/insert reviews and execute the RPC;
- the RPC is `SECURITY INVOKER` with `search_path` set to empty;
- draft/review identity is protected by a composite foreign key and uniqueness;
- approval and rejection are allowed append-only history actions; and
- the composite foreign key has a covering B-tree index.

Supabase's security advisor reports only informational no-policy notices. They
match the intentional backend-only design: browser roles have no grants and no
policies. The performance advisor no longer reports an unindexed foreign key.
Its remaining unused-index notices are expected in this new, nearly empty demo
database.

## Guarded live demo

`scripts/run_live_demo.py` requires both `--confirm-live-write` and the exact
ProofShield project reference. It rejects a missing/short operator secret,
refuses a different Supabase project, labels every synthetic identifier, and
prints no credentials.

The retained demonstration record is:

```text
case:    demo_disp_m9_20260825
draft:   draft_db944547a97e044397e268cbd9c3dee3
review:  review_2fc33d2515badc19c5391333431d22b2
```

The run proved:

1. two source files reached private Supabase Storage;
2. two human-confirmed evidence records produced `SAFE_TO_DRAFT`;
3. an unauthorized review returned HTTP 401;
4. packet export before approval returned HTTP 409;
5. approval was stored once and an exact retry was idempotent;
6. the packet contained the case, draft, review, response, manifest, and both
   cited evidence files;
7. every evidence SHA-256 matched its manifest entry;
8. repeated packet downloads were byte-identical; and
9. the append-only history contained exactly one `DRAFT_APPROVED` event.

The packet SHA-256 was:

```text
c2183b5350bd77798d535da2cbaf4f899d12428f3527d288cbf7de36fbf3f412
```

An independent SQL query confirmed one case, two files, two evidence records,
one draft, one approved review, and one approval-history entry.

## Retention and security boundary

The synthetic case is intentionally retained so the local merchant dashboard
has a realistic end-to-end demonstration. It is labelled `demo_*` throughout
and contains no customer data. The process-only operator secret used for this
verification was not saved to `.env`, Git, Supabase, or the result output.

Before deployment, replace the shared operator secret with named Supabase Auth
identities, case ownership, and narrow RLS policies. Razorpay submission is not
implemented and remains out of scope.

## Next milestone

Add named operator authentication and ownership-aware authorization locally,
then run the dashboard against the retained demo. Deployment remains a later,
explicit decision.
