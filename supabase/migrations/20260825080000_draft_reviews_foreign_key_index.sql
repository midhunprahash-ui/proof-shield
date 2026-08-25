-- Cover the composite draft-review foreign key used for parent delete checks.

create index proofshield_draft_reviews_draft_case_idx
  on public.proofshield_draft_reviews (draft_id, dispute_id);
