-- Named Supabase Auth operators replace the shared review secret.

create table public.proofshield_operators (
  user_id uuid primary key references auth.users(id) on delete restrict,
  email text not null unique,
  display_name text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  constraint proofshield_operators_email_check check (
    char_length(email) between 3 and 320
    and email = lower(btrim(email))
  ),
  constraint proofshield_operators_display_name_check check (
    char_length(display_name) between 1 and 200
    and display_name = btrim(display_name)
  )
);

alter table public.proofshield_operators enable row level security;

revoke all on table public.proofshield_operators
  from public, anon, authenticated, service_role;
grant select, insert, update on table public.proofshield_operators to service_role;
grant select on table public.proofshield_operators to authenticated;

alter table public.proofshield_cases
  add column owner_id uuid
  references public.proofshield_operators(user_id)
  on delete restrict;

create index proofshield_cases_owner_updated_idx
  on public.proofshield_cases (owner_id, updated_at desc, dispute_id)
  where owner_id is not null;

alter table public.proofshield_draft_reviews
  add column reviewer_user_id uuid
  references public.proofshield_operators(user_id)
  on delete restrict;

create index proofshield_draft_reviews_reviewer_user_idx
  on public.proofshield_draft_reviews (reviewer_user_id, created_at desc)
  where reviewer_user_id is not null;

alter table public.proofshield_case_history
  drop constraint proofshield_case_history_action_check;

alter table public.proofshield_case_history
  add constraint proofshield_case_history_action_check check (
    action in (
      'CASE_CREATED',
      'CASE_CLAIMED',
      'FILE_UPLOADED',
      'EVIDENCE_ADDED',
      'ASSESSED',
      'DRAFT_CREATED',
      'DRAFT_APPROVED',
      'DRAFT_REJECTED'
    )
  );

alter table public.proofshield_draft_reviews
  drop constraint proofshield_draft_reviews_json_check;

alter table public.proofshield_draft_reviews
  add constraint proofshield_draft_reviews_json_check check (
    jsonb_typeof(review_json) = 'object'
    and review_json ->> 'dispute_id' = dispute_id
    and review_json ->> 'draft_id' = draft_id
    and review_json ->> 'review_id' = review_id
    and review_json ->> 'decision' = decision
    and (review_json ->> 'reviewer_user_id')
      is not distinct from reviewer_user_id::text
    and review_json ->> 'reviewer_label' = reviewer_label
    and (review_json ->> 'note') is not distinct from note
    and review_json ->> 'request_sha256' = request_sha256
  );

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
grant usage on schema private to authenticated;

create or replace function private.proofshield_operator_owns_case(
  p_dispute_id text
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.proofshield_cases as c
    join public.proofshield_operators as o on o.user_id = c.owner_id
    where c.dispute_id = p_dispute_id
      and o.active
      and c.owner_id = (select auth.uid())
  );
$$;

revoke execute on function private.proofshield_operator_owns_case(text)
  from public, anon;
grant execute on function private.proofshield_operator_owns_case(text)
  to authenticated;

create policy proofshield_operators_select_self
on public.proofshield_operators
for select
to authenticated
using (
  active
  and user_id = (select auth.uid())
);

create policy proofshield_cases_select_owned
on public.proofshield_cases
for select
to authenticated
using (
  owner_id = (select auth.uid())
  and (select private.proofshield_operator_owns_case(dispute_id))
);

create policy proofshield_evidence_select_owned
on public.proofshield_evidence
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

create policy proofshield_evidence_files_select_owned
on public.proofshield_evidence_files
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

create policy proofshield_case_history_select_owned
on public.proofshield_case_history
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

create policy proofshield_response_drafts_select_owned
on public.proofshield_response_drafts
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

create policy proofshield_draft_reviews_select_owned
on public.proofshield_draft_reviews
for select
to authenticated
using ((select private.proofshield_operator_owns_case(dispute_id)));

grant select on table public.proofshield_cases to authenticated;
grant select on table public.proofshield_evidence to authenticated;
grant select on table public.proofshield_evidence_files to authenticated;
grant select on table public.proofshield_case_history to authenticated;
grant select on table public.proofshield_response_drafts to authenticated;
grant select on table public.proofshield_draft_reviews to authenticated;

create or replace function public.proofshield_save_case(
  p_dispute_id text,
  p_payment_id text,
  p_order_id text,
  p_reason text,
  p_disputed_amount text,
  p_currency text,
  p_core_json jsonb,
  p_core_sha256 text,
  p_source text,
  p_owner_id uuid
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_inserted bigint;
  v_existing_sha256 text;
  v_existing_owner uuid;
begin
  if p_owner_id is not null and not exists (
    select 1
    from public.proofshield_operators as o
    where o.user_id = p_owner_id and o.active
  ) then
    return 'OWNER_NOT_AUTHORIZED';
  end if;

  insert into public.proofshield_cases (
    dispute_id,
    payment_id,
    order_id,
    reason,
    disputed_amount,
    currency,
    core_json,
    core_sha256,
    source,
    owner_id
  ) values (
    p_dispute_id,
    p_payment_id,
    p_order_id,
    p_reason,
    p_disputed_amount::numeric,
    p_currency,
    p_core_json,
    p_core_sha256,
    p_source,
    p_owner_id
  )
  on conflict (dispute_id) do nothing;

  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    insert into public.proofshield_case_history (dispute_id, action, detail)
    values (p_dispute_id, 'CASE_CREATED', format('Case created from %s.', p_source));
    return 'CREATED';
  end if;

  select c.core_sha256, c.owner_id
  into v_existing_sha256, v_existing_owner
  from public.proofshield_cases as c
  where c.dispute_id = p_dispute_id;

  if v_existing_sha256 = p_core_sha256
    and (
      p_owner_id is null
      or v_existing_owner is not distinct from p_owner_id
    )
  then
    return 'EXISTS';
  end if;
  if v_existing_sha256 = p_core_sha256 then
    return 'OWNER_CONFLICT';
  end if;
  return 'CONFLICT';
end;
$$;

create or replace function public.proofshield_list_cases(p_owner_id uuid)
returns table (
  dispute_id text,
  payment_id text,
  order_id text,
  reason text,
  disputed_amount text,
  currency text,
  evidence_count bigint,
  updated_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    c.dispute_id,
    c.payment_id,
    c.order_id,
    c.reason,
    c.disputed_amount::text,
    c.currency,
    count(e.evidence_id)::bigint,
    c.updated_at
  from public.proofshield_cases as c
  left join public.proofshield_evidence as e on e.dispute_id = c.dispute_id
  where p_owner_id is null or c.owner_id = p_owner_id
  group by c.dispute_id
  order by c.updated_at desc, c.dispute_id;
$$;

create or replace function public.proofshield_list_unassigned_cases()
returns table (
  dispute_id text,
  payment_id text,
  order_id text,
  reason text,
  disputed_amount text,
  currency text,
  evidence_count bigint,
  updated_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
  select
    c.dispute_id,
    c.payment_id,
    c.order_id,
    c.reason,
    c.disputed_amount::text,
    c.currency,
    count(e.evidence_id)::bigint,
    c.updated_at
  from public.proofshield_cases as c
  left join public.proofshield_evidence as e on e.dispute_id = c.dispute_id
  where c.owner_id is null
  group by c.dispute_id
  order by c.updated_at desc, c.dispute_id;
$$;

create or replace function public.proofshield_claim_case(
  p_dispute_id text,
  p_owner_id uuid
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_claimed_id text;
  v_existing_owner uuid;
begin
  if not exists (
    select 1
    from public.proofshield_operators as o
    where o.user_id = p_owner_id and o.active
  ) then
    return 'OWNER_NOT_AUTHORIZED';
  end if;

  update public.proofshield_cases as c
  set owner_id = p_owner_id,
      updated_at = now()
  where c.dispute_id = p_dispute_id
    and c.owner_id is null
  returning c.dispute_id into v_claimed_id;

  if found then
    insert into public.proofshield_case_history (
      dispute_id,
      action,
      reference_id,
      detail
    ) values (
      p_dispute_id,
      'CASE_CLAIMED',
      p_owner_id::text,
      'Case claimed by an authenticated operator.'
    );
    return 'CLAIMED';
  end if;

  select c.owner_id
  into v_existing_owner
  from public.proofshield_cases as c
  where c.dispute_id = p_dispute_id;

  if not found then
    return 'CASE_NOT_FOUND';
  end if;
  if v_existing_owner = p_owner_id then
    return 'EXISTS';
  end if;
  return 'ALREADY_CLAIMED';
end;
$$;

create or replace function public.proofshield_review_response_draft(
  p_draft_id text,
  p_review_id text,
  p_decision text,
  p_reviewer_user_id uuid,
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
  v_expected_label text;
  v_inserted bigint;
  v_existing_request_sha256 text;
begin
  select o.display_name
  into v_expected_label
  from public.proofshield_operators as o
  where o.user_id = p_reviewer_user_id and o.active;

  if not found
    or p_draft_id is null
    or p_review_id is null
    or char_length(p_review_id) not between 1 and 200
    or p_decision is null
    or p_decision not in ('APPROVED', 'REJECTED')
    or p_reviewer_label is null
    or p_reviewer_label <> v_expected_label
    or (p_note is not null and char_length(p_note) not between 1 and 2000)
    or (p_decision = 'REJECTED' and p_note is null)
    or p_request_sha256 is null
    or p_request_sha256 !~ '^[0-9a-f]{64}$'
    or p_review_json is null
  then
    return 'REJECTED';
  end if;

  select d.dispute_id
  into v_dispute_id
  from public.proofshield_response_drafts as d
  join public.proofshield_cases as c on c.dispute_id = d.dispute_id
  where d.draft_id = p_draft_id
    and c.owner_id = p_reviewer_user_id;

  if not found then
    return 'DRAFT_NOT_FOUND';
  end if;

  if p_review_json ->> 'dispute_id' <> v_dispute_id
    or p_review_json ->> 'draft_id' <> p_draft_id
    or p_review_json ->> 'review_id' <> p_review_id
    or p_review_json ->> 'decision' <> p_decision
    or p_review_json ->> 'reviewer_user_id' <> p_reviewer_user_id::text
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
    reviewer_user_id,
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
    p_reviewer_user_id,
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

  select r.request_sha256
  into v_existing_request_sha256
  from public.proofshield_draft_reviews as r
  where r.draft_id = p_draft_id;

  if v_existing_request_sha256 = p_request_sha256 then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

revoke execute on function public.proofshield_save_case(
  text, text, text, text, text, text, jsonb, text, text, uuid
) from public, anon, authenticated;
grant execute on function public.proofshield_save_case(
  text, text, text, text, text, text, jsonb, text, text, uuid
) to service_role;

revoke execute on function public.proofshield_list_cases(uuid)
  from public, anon, authenticated;
grant execute on function public.proofshield_list_cases(uuid)
  to service_role;

revoke execute on function public.proofshield_list_unassigned_cases()
  from public, anon, authenticated;
grant execute on function public.proofshield_list_unassigned_cases()
  to service_role;

revoke execute on function public.proofshield_claim_case(text, uuid)
  from public, anon, authenticated;
grant execute on function public.proofshield_claim_case(text, uuid)
  to service_role;

revoke execute on function public.proofshield_review_response_draft(
  text, text, text, uuid, text, text, text, jsonb, timestamptz
) from public, anon, authenticated;
grant execute on function public.proofshield_review_response_draft(
  text, text, text, uuid, text, text, text, jsonb, timestamptz
) to service_role;

drop function public.proofshield_save_case(
  text, text, text, text, text, text, jsonb, text, text
);
drop function public.proofshield_list_cases();
drop function public.proofshield_review_response_draft(
  text, text, text, text, text, text, jsonb, timestamptz
);
