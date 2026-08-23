-- Evidence-grounded response drafts remain backend-only and human-approved.

create table public.proofshield_response_drafts (
  draft_id text primary key,
  dispute_id text not null references public.proofshield_cases(dispute_id) on delete restrict,
  decision text not null,
  status text not null,
  generator text not null,
  input_sha256 text not null,
  content_sha256 text not null,
  draft_json jsonb not null,
  created_at timestamptz not null,
  constraint proofshield_response_drafts_id_length
    check (char_length(draft_id) between 1 and 200),
  constraint proofshield_response_drafts_decision_check
    check (decision = 'SAFE_TO_DRAFT'),
  constraint proofshield_response_drafts_status_check
    check (status = 'PENDING_HUMAN_APPROVAL'),
  constraint proofshield_response_drafts_generator_length
    check (char_length(generator) between 1 and 100),
  constraint proofshield_response_drafts_input_sha256_check
    check (input_sha256 ~ '^[0-9a-f]{64}$'),
  constraint proofshield_response_drafts_content_sha256_check
    check (content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint proofshield_response_drafts_json_check check (
    jsonb_typeof(draft_json) = 'object'
    and draft_json ->> 'draft_id' = draft_id
    and draft_json ->> 'dispute_id' = dispute_id
    and draft_json ->> 'decision' = decision
    and draft_json ->> 'status' = status
    and draft_json ->> 'generator' = generator
    and draft_json ->> 'input_sha256' = input_sha256
    and draft_json ->> 'content_sha256' = content_sha256
    and jsonb_typeof(draft_json -> 'citations') = 'array'
    and jsonb_array_length(draft_json -> 'citations') >= 2
    and (draft_json ->> 'human_approval_required')::boolean is true
  )
);

create index proofshield_response_drafts_dispute_id_idx
  on public.proofshield_response_drafts (dispute_id, created_at desc, draft_id);

alter table public.proofshield_case_history
  drop constraint proofshield_case_history_action_check;

alter table public.proofshield_case_history
  add constraint proofshield_case_history_action_check check (
    action in (
      'CASE_CREATED',
      'FILE_UPLOADED',
      'EVIDENCE_ADDED',
      'ASSESSED',
      'DRAFT_CREATED'
    )
  );

alter table public.proofshield_response_drafts enable row level security;

revoke all on table public.proofshield_response_drafts
  from anon, authenticated, service_role;
grant select, insert on table public.proofshield_response_drafts to service_role;

create or replace function public.proofshield_save_response_draft(
  p_draft_id text,
  p_dispute_id text,
  p_decision text,
  p_status text,
  p_generator text,
  p_input_sha256 text,
  p_content_sha256 text,
  p_draft_json jsonb,
  p_created_at timestamptz
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_inserted bigint;
  v_existing_input_sha256 text;
  v_existing_content_sha256 text;
begin
  if p_decision <> 'SAFE_TO_DRAFT'
    or p_status <> 'PENDING_HUMAN_APPROVAL'
  then
    return 'REJECTED';
  end if;

  if not exists (
    select 1
    from public.proofshield_cases
    where dispute_id = p_dispute_id
  ) then
    return 'CASE_NOT_FOUND';
  end if;

  insert into public.proofshield_response_drafts (
    draft_id,
    dispute_id,
    decision,
    status,
    generator,
    input_sha256,
    content_sha256,
    draft_json,
    created_at
  ) values (
    p_draft_id,
    p_dispute_id,
    p_decision,
    p_status,
    p_generator,
    p_input_sha256,
    p_content_sha256,
    p_draft_json,
    p_created_at
  )
  on conflict (draft_id) do nothing;

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
      'DRAFT_CREATED',
      p_draft_id,
      p_created_at,
      format(
        'Draft created; generator=%s; status=%s; decision=%s.',
        p_generator,
        p_status,
        p_decision
      )
    );
    update public.proofshield_cases
    set updated_at = p_created_at
    where dispute_id = p_dispute_id;
    return 'CREATED';
  end if;

  select input_sha256, content_sha256
  into v_existing_input_sha256, v_existing_content_sha256
  from public.proofshield_response_drafts
  where draft_id = p_draft_id;

  if v_existing_input_sha256 = p_input_sha256
    and v_existing_content_sha256 = p_content_sha256
  then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

revoke execute on function public.proofshield_save_response_draft(
  text, text, text, text, text, text, text, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.proofshield_save_response_draft(
  text, text, text, text, text, text, text, jsonb, timestamptz
) to service_role;
