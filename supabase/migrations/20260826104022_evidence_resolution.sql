-- Append-only operator resolutions for incorrect or superseded evidence.
-- Original evidence rows remain immutable and browser roles remain read-only.

alter table public.proofshield_evidence
  add constraint proofshield_evidence_id_dispute_unique
  unique (evidence_id, dispute_id);

create table public.proofshield_evidence_resolutions (
  resolution_id text primary key,
  dispute_id text not null
    references public.proofshield_cases(dispute_id) on delete restrict,
  evidence_id text not null unique,
  action text not null,
  replacement_evidence_id text,
  reason text not null,
  resolved_by uuid not null
    references public.proofshield_operators(user_id) on delete restrict,
  request_sha256 text not null,
  resolution_json jsonb not null,
  created_at timestamptz not null,
  constraint proofshield_evidence_resolutions_source_fk foreign key (
    evidence_id,
    dispute_id
  ) references public.proofshield_evidence(evidence_id, dispute_id)
    on delete restrict,
  constraint proofshield_evidence_resolutions_replacement_fk foreign key (
    replacement_evidence_id,
    dispute_id
  ) references public.proofshield_evidence(evidence_id, dispute_id)
    on delete restrict,
  constraint proofshield_evidence_resolutions_id_length check (
    char_length(resolution_id) between 1 and 200
  ),
  constraint proofshield_evidence_resolutions_action_check check (
    action in ('EXCLUDED_INCORRECT', 'SUPERSEDED')
  ),
  constraint proofshield_evidence_resolutions_replacement_check check (
    (
      action = 'EXCLUDED_INCORRECT'
      and replacement_evidence_id is null
    )
    or (
      action = 'SUPERSEDED'
      and replacement_evidence_id is not null
      and replacement_evidence_id <> evidence_id
    )
  ),
  constraint proofshield_evidence_resolutions_reason_check check (
    char_length(reason) between 10 and 2000
    and reason = btrim(reason)
  ),
  constraint proofshield_evidence_resolutions_sha256_check check (
    request_sha256 ~ '^[0-9a-f]{64}$'
  ),
  constraint proofshield_evidence_resolutions_json_check check (
    jsonb_typeof(resolution_json) = 'object'
    and resolution_json ->> 'resolution_id' = resolution_id
    and resolution_json ->> 'dispute_id' = dispute_id
    and resolution_json ->> 'evidence_id' = evidence_id
    and resolution_json ->> 'action' = action
    and (resolution_json ->> 'replacement_evidence_id')
      is not distinct from replacement_evidence_id
    and resolution_json ->> 'reason' = reason
    and resolution_json ->> 'resolved_by' = resolved_by::text
    and resolution_json ->> 'request_sha256' = request_sha256
  )
);

create index proofshield_evidence_resolutions_dispute_idx
  on public.proofshield_evidence_resolutions (
    dispute_id,
    created_at,
    resolution_id
  );

create index proofshield_evidence_resolutions_replacement_idx
  on public.proofshield_evidence_resolutions (replacement_evidence_id)
  where replacement_evidence_id is not null;

create index proofshield_evidence_resolutions_resolver_idx
  on public.proofshield_evidence_resolutions (resolved_by, created_at desc);

alter table public.proofshield_evidence_resolutions enable row level security;

revoke all on table public.proofshield_evidence_resolutions
  from public, anon, authenticated, service_role;
grant select, insert on table public.proofshield_evidence_resolutions
  to service_role;
grant select on table public.proofshield_evidence_resolutions
  to authenticated;

create policy proofshield_evidence_resolutions_select_owned
on public.proofshield_evidence_resolutions
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

alter table public.proofshield_case_history
  drop constraint proofshield_case_history_action_check;

alter table public.proofshield_case_history
  add constraint proofshield_case_history_action_check check (
    action in (
      'CASE_CREATED',
      'CASE_CLAIMED',
      'FILE_UPLOADED',
      'EVIDENCE_ADDED',
      'EVIDENCE_RESOLVED',
      'ASSESSED',
      'DRAFT_CREATED',
      'DRAFT_APPROVED',
      'DRAFT_REJECTED'
    )
  );

create or replace function public.proofshield_resolve_evidence(
  p_dispute_id text,
  p_evidence_id text,
  p_resolution_id text,
  p_action text,
  p_replacement_evidence_id text,
  p_reason text,
  p_resolved_by uuid,
  p_request_sha256 text,
  p_resolution_json jsonb,
  p_created_at timestamptz
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_evidence_type text;
  v_replacement_type text;
  v_inserted bigint;
  v_existing_request_sha256 text;
begin
  if p_dispute_id is null
    or p_evidence_id is null
    or p_resolution_id is null
    or char_length(p_resolution_id) not between 1 and 200
    or p_action not in ('EXCLUDED_INCORRECT', 'SUPERSEDED')
    or p_reason is null
    or char_length(p_reason) not between 10 and 2000
    or p_reason <> btrim(p_reason)
    or p_resolved_by is null
    or p_request_sha256 is null
    or p_request_sha256 !~ '^[0-9a-f]{64}$'
    or p_resolution_json is null
    or p_created_at is null
    or (p_action = 'EXCLUDED_INCORRECT' and p_replacement_evidence_id is not null)
    or (p_action = 'SUPERSEDED' and p_replacement_evidence_id is null)
    or p_replacement_evidence_id = p_evidence_id
  then
    return 'REJECTED';
  end if;

  if not exists (
    select 1
    from public.proofshield_cases as c
    join public.proofshield_operators as o on o.user_id = c.owner_id
    where c.dispute_id = p_dispute_id
      and c.owner_id = p_resolved_by
      and o.active
  ) then
    return 'CASE_NOT_FOUND';
  end if;

  select e.document_json ->> 'evidence_type'
  into v_evidence_type
  from public.proofshield_evidence as e
  where e.evidence_id = p_evidence_id
    and e.dispute_id = p_dispute_id
  for update of e;

  if not found then
    return 'EVIDENCE_NOT_FOUND';
  end if;

  if exists (
    select 1
    from public.proofshield_evidence_resolutions as r
    where r.replacement_evidence_id = p_evidence_id
  ) then
    return 'TARGET_IS_REPLACEMENT';
  end if;

  if p_action = 'SUPERSEDED' then
    select e.document_json ->> 'evidence_type'
    into v_replacement_type
    from public.proofshield_evidence as e
    where e.evidence_id = p_replacement_evidence_id
      and e.dispute_id = p_dispute_id
    for update of e;

    if not found then
      return 'REPLACEMENT_NOT_FOUND';
    end if;
    if v_replacement_type is distinct from v_evidence_type then
      return 'TYPE_MISMATCH';
    end if;
    if exists (
      select 1
      from public.proofshield_evidence_resolutions as r
      where r.evidence_id = p_replacement_evidence_id
    ) then
      return 'REPLACEMENT_RESOLVED';
    end if;
  end if;

  if p_resolution_json ->> 'resolution_id' <> p_resolution_id
    or p_resolution_json ->> 'dispute_id' <> p_dispute_id
    or p_resolution_json ->> 'evidence_id' <> p_evidence_id
    or p_resolution_json ->> 'action' <> p_action
    or (p_resolution_json ->> 'replacement_evidence_id')
      is distinct from p_replacement_evidence_id
    or p_resolution_json ->> 'reason' <> p_reason
    or p_resolution_json ->> 'resolved_by' <> p_resolved_by::text
    or p_resolution_json ->> 'request_sha256' <> p_request_sha256
  then
    return 'REJECTED';
  end if;

  insert into public.proofshield_evidence_resolutions (
    resolution_id,
    dispute_id,
    evidence_id,
    action,
    replacement_evidence_id,
    reason,
    resolved_by,
    request_sha256,
    resolution_json,
    created_at
  ) values (
    p_resolution_id,
    p_dispute_id,
    p_evidence_id,
    p_action,
    p_replacement_evidence_id,
    p_reason,
    p_resolved_by,
    p_request_sha256,
    p_resolution_json,
    p_created_at
  )
  on conflict do nothing;

  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    insert into public.proofshield_case_history (
      dispute_id,
      action,
      reference_id,
      recorded_at,
      detail
    ) values (
      p_dispute_id,
      'EVIDENCE_RESOLVED',
      p_resolution_id,
      p_created_at,
      format(
        'Evidence %s; action=%s; replacement=%s.',
        p_evidence_id,
        p_action,
        coalesce(p_replacement_evidence_id, 'none')
      )
    );
    update public.proofshield_cases
    set updated_at = p_created_at
    where dispute_id = p_dispute_id;
    return 'CREATED';
  end if;

  select r.request_sha256
  into v_existing_request_sha256
  from public.proofshield_evidence_resolutions as r
  where r.evidence_id = p_evidence_id;

  if v_existing_request_sha256 = p_request_sha256 then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

revoke execute on function public.proofshield_resolve_evidence(
  text, text, text, text, text, text, uuid, text, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.proofshield_resolve_evidence(
  text, text, text, text, text, text, uuid, text, jsonb, timestamptz
) to service_role;
