-- Cover both composite foreign keys used by evidence resolutions.
-- The table is empty at activation, so regular transactional index creation
-- avoids the restrictions of CREATE INDEX CONCURRENTLY.

create index proofshield_evidence_resolutions_source_case_idx
  on public.proofshield_evidence_resolutions (evidence_id, dispute_id);

create index proofshield_evidence_resolutions_replacement_case_idx
  on public.proofshield_evidence_resolutions (
    replacement_evidence_id,
    dispute_id
  );
