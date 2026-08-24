-- Immutable human decisions gate evidence-packet export.

alter table public.proofshield_response_drafts
  add constraint proofshield_response_drafts_id_dispute_unique
  unique (draft_id, dispute_id);

create table public.proofshield_draft_reviews (
  review_id text primary key,
  draft_id text not null unique,
  dispute_id text not null,
  decision text not null,
  reviewer_label text not null,
  note text,
  request_sha256 text not null,
  review_json jsonb not null,
  created_at timestamptz not null,
  constraint proofshield_draft_reviews_draft_case_fkey
    foreign key (draft_id, dispute_id)
    references public.proofshield_response_drafts(draft_id, dispute_id)
    on delete restrict,
  constraint proofshield_draft_reviews_review_id_length
    check (char_length(review_id) between 1 and 200),
  constraint proofshield_draft_reviews_decision_check
    check (decision in ('APPROVED', 'REJECTED')),
  constraint proofshield_draft_reviews_reviewer_label_check
    check (
      char_length(reviewer_label) between 1 and 200
      and reviewer_label = btrim(reviewer_label)
    ),
  constraint proofshield_draft_reviews_note_check
    check (
      (note is null or char_length(note) between 1 and 2000)
      and (decision <> 'REJECTED' or note is not null)
    ),
  constraint proofshield_draft_reviews_request_sha256_check
    check (request_sha256 ~ '^[0-9a-f]{64}$'),
  constraint proofshield_draft_reviews_json_check check (
    jsonb_typeof(review_json) = 'object'
    and review_json ->> 'dispute_id' = dispute_id
    and review_json ->> 'draft_id' = draft_id
    and review_json ->> 'review_id' = review_id
    and review_json ->> 'decision' = decision
    and review_json ->> 'reviewer_label' = reviewer_label
    and (review_json ->> 'note') is not distinct from note
    and review_json ->> 'request_sha256' = request_sha256
  )
);

alter table public.proofshield_case_history
  drop constraint proofshield_case_history_action_check;

alter table public.proofshield_case_history
  add constraint proofshield_case_history_action_check check (
    action in (
      'CASE_CREATED',
      'FILE_UPLOADED',
      'EVIDENCE_ADDED',
      'ASSESSED',
      'DRAFT_CREATED',
      'DRAFT_APPROVED',
      'DRAFT_REJECTED'
    )
  );

alter table public.proofshield_draft_reviews enable row level security;

revoke all on table public.proofshield_draft_reviews
  from anon, authenticated, service_role;
grant select, insert on table public.proofshield_draft_reviews to service_role;

create or replace function public.proofshield_review_response_draft(
  p_draft_id text,
  p_review_id text,
  p_decision text,
  p_reviewer_label text,
  p_note text,
  p_request_sha256 text,
  p_review_json jsonb,
  p_created_at timestamptz
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_dispute_id text;
  v_inserted bigint;
  v_existing_request_sha256 text;
begin
  if p_draft_id is null
    or p_review_id is null
    or char_length(p_review_id) not between 1 and 200
    or p_decision is null
    or p_decision not in ('APPROVED', 'REJECTED')
    or p_reviewer_label is null
    or char_length(p_reviewer_label) not between 1 and 200
    or p_reviewer_label <> btrim(p_reviewer_label)
    or (p_note is not null and char_length(p_note) not between 1 and 2000)
    or (p_decision = 'REJECTED' and p_note is null)
    or p_request_sha256 is null
    or p_request_sha256 !~ '^[0-9a-f]{64}$'
    or p_review_json is null
  then
    return 'REJECTED';
  end if;

  select dispute_id
  into v_dispute_id
  from public.proofshield_response_drafts
  where draft_id = p_draft_id;

  if not found then
    return 'DRAFT_NOT_FOUND';
  end if;

  if p_review_json ->> 'dispute_id' <> v_dispute_id
    or p_review_json ->> 'draft_id' <> p_draft_id
    or p_review_json ->> 'review_id' <> p_review_id
    or p_review_json ->> 'decision' <> p_decision
    or p_review_json ->> 'reviewer_label' <> p_reviewer_label
    or (p_review_json ->> 'note') is distinct from p_note
    or p_review_json ->> 'request_sha256' <> p_request_sha256
  then
    return 'REJECTED';
  end if;

  insert into public.proofshield_draft_reviews (
    review_id,
    draft_id,
    dispute_id,
    decision,
    reviewer_label,
    note,
    request_sha256,
    review_json,
    created_at
  ) values (
    p_review_id,
    p_draft_id,
    v_dispute_id,
    p_decision,
    p_reviewer_label,
    p_note,
    p_request_sha256,
    p_review_json,
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
      v_dispute_id,
      case
        when p_decision = 'APPROVED' then 'DRAFT_APPROVED'
        else 'DRAFT_REJECTED'
      end,
      p_review_id,
      p_created_at,
      format(
        'Draft %s; reviewer_label=%s.',
        lower(p_decision),
        p_reviewer_label
      )
    );
    update public.proofshield_cases
    set updated_at = p_created_at
    where dispute_id = v_dispute_id;
    return 'CREATED';
  end if;

  select request_sha256
  into v_existing_request_sha256
  from public.proofshield_draft_reviews
  where draft_id = p_draft_id;

  if v_existing_request_sha256 = p_request_sha256 then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

revoke execute on function public.proofshield_review_response_draft(
  text, text, text, text, text, text, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.proofshield_review_response_draft(
  text, text, text, text, text, text, jsonb, timestamptz
) to service_role;
