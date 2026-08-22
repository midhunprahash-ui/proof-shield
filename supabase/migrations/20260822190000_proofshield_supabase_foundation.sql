-- ProofShield's backend-only Supabase persistence foundation.
-- No anon/authenticated policies are created: the trusted backend is the only client initially.

create table if not exists public.proofshield_cases (
  dispute_id text primary key,
  payment_id text not null,
  order_id text not null,
  reason text not null,
  disputed_amount numeric(18, 2) not null,
  currency text not null,
  core_json jsonb not null,
  core_sha256 text not null,
  source text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint proofshield_cases_dispute_id_length check (char_length(dispute_id) between 1 and 200),
  constraint proofshield_cases_payment_id_length check (char_length(payment_id) between 1 and 200),
  constraint proofshield_cases_order_id_length check (char_length(order_id) between 1 and 200),
  constraint proofshield_cases_reason_check check (reason in ('PRODUCT_NOT_RECEIVED', 'OTHER')),
  constraint proofshield_cases_amount_positive check (disputed_amount > 0),
  constraint proofshield_cases_currency_check check (currency ~ '^[A-Z]{3}$'),
  constraint proofshield_cases_core_sha256_check check (core_sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists proofshield_cases_updated_at_idx
  on public.proofshield_cases (updated_at desc, dispute_id);

create table if not exists public.proofshield_evidence (
  evidence_id text primary key,
  dispute_id text not null references public.proofshield_cases(dispute_id) on delete restrict,
  document_json jsonb not null,
  document_sha256 text not null,
  created_at timestamptz not null default now(),
  constraint proofshield_evidence_id_length check (char_length(evidence_id) between 1 and 200),
  constraint proofshield_evidence_sha256_check check (document_sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists proofshield_evidence_dispute_id_idx
  on public.proofshield_evidence (dispute_id, created_at, evidence_id);

create table if not exists public.proofshield_evidence_files (
  file_id text primary key,
  dispute_id text not null references public.proofshield_cases(dispute_id) on delete restrict,
  original_name text not null,
  content_type text not null,
  size_bytes bigint not null,
  sha256 text not null,
  storage_key text not null unique,
  created_at timestamptz not null default now(),
  constraint proofshield_evidence_files_id_length check (char_length(file_id) between 1 and 200),
  constraint proofshield_evidence_files_name_length check (char_length(original_name) between 1 and 255),
  constraint proofshield_evidence_files_content_type_check check (
    content_type in ('application/json', 'application/pdf', 'image/jpeg', 'image/png', 'text/plain')
  ),
  constraint proofshield_evidence_files_size_check check (size_bytes between 1 and 5000000),
  constraint proofshield_evidence_files_sha256_check check (sha256 ~ '^[0-9a-f]{64}$')
);

create index if not exists proofshield_evidence_files_dispute_id_idx
  on public.proofshield_evidence_files (dispute_id, created_at, file_id);

create table if not exists public.proofshield_case_history (
  sequence bigint generated always as identity primary key,
  dispute_id text not null references public.proofshield_cases(dispute_id) on delete restrict,
  action text not null,
  reference_id text,
  recorded_at timestamptz not null default now(),
  detail text not null,
  constraint proofshield_case_history_action_check check (
    action in ('CASE_CREATED', 'FILE_UPLOADED', 'EVIDENCE_ADDED', 'ASSESSED')
  )
);

create index if not exists proofshield_case_history_dispute_id_idx
  on public.proofshield_case_history (dispute_id, sequence);

create table if not exists public.proofshield_webhook_events (
  event_id text primary key,
  body_sha256 text not null,
  event_type text,
  status text not null,
  dispute_id text,
  decision text,
  detail text not null,
  first_received_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint proofshield_webhook_events_id_length check (char_length(event_id) between 1 and 200),
  constraint proofshield_webhook_events_sha256_check check (body_sha256 ~ '^[0-9a-f]{64}$'),
  constraint proofshield_webhook_events_status_check check (
    status in ('RECEIVED', 'PROCESSED', 'IGNORED', 'FAILED', 'NEEDS_ENRICHMENT')
  ),
  constraint proofshield_webhook_events_decision_check check (
    decision is null or decision in ('SAFE_TO_DRAFT', 'NEEDS_REVIEW', 'INSUFFICIENT_EVIDENCE')
  )
);

create index if not exists proofshield_webhook_events_status_idx
  on public.proofshield_webhook_events (status, updated_at desc);

create table if not exists public.proofshield_webhook_audit (
  sequence bigint generated always as identity primary key,
  event_id text not null,
  body_sha256 text not null,
  status text not null,
  recorded_at timestamptz not null default now(),
  event_type text,
  dispute_id text,
  decision text,
  detail text not null,
  constraint proofshield_webhook_audit_event_id_length check (char_length(event_id) between 1 and 200),
  constraint proofshield_webhook_audit_sha256_check check (body_sha256 ~ '^[0-9a-f]{64}$'),
  constraint proofshield_webhook_audit_status_check check (
    status in ('RECEIVED', 'PROCESSED', 'DUPLICATE', 'IGNORED', 'REJECTED', 'FAILED', 'NEEDS_ENRICHMENT')
  ),
  constraint proofshield_webhook_audit_decision_check check (
    decision is null or decision in ('SAFE_TO_DRAFT', 'NEEDS_REVIEW', 'INSUFFICIENT_EVIDENCE')
  )
);

create index if not exists proofshield_webhook_audit_event_id_idx
  on public.proofshield_webhook_audit (event_id, sequence);

alter table public.proofshield_cases enable row level security;
alter table public.proofshield_evidence enable row level security;
alter table public.proofshield_evidence_files enable row level security;
alter table public.proofshield_case_history enable row level security;
alter table public.proofshield_webhook_events enable row level security;
alter table public.proofshield_webhook_audit enable row level security;

revoke all on table public.proofshield_cases from anon, authenticated, service_role;
revoke all on table public.proofshield_evidence from anon, authenticated, service_role;
revoke all on table public.proofshield_evidence_files from anon, authenticated, service_role;
revoke all on table public.proofshield_case_history from anon, authenticated, service_role;
revoke all on table public.proofshield_webhook_events from anon, authenticated, service_role;
revoke all on table public.proofshield_webhook_audit from anon, authenticated, service_role;

grant select, insert, update on table public.proofshield_cases to service_role;
grant select, insert on table public.proofshield_evidence to service_role;
grant select, insert on table public.proofshield_evidence_files to service_role;
grant select, insert on table public.proofshield_case_history to service_role;
grant select, insert, update on table public.proofshield_webhook_events to service_role;
grant select, insert on table public.proofshield_webhook_audit to service_role;
grant usage, select on sequence public.proofshield_case_history_sequence_seq to service_role;
grant usage, select on sequence public.proofshield_webhook_audit_sequence_seq to service_role;

create or replace function public.proofshield_save_case(
  p_dispute_id text,
  p_payment_id text,
  p_order_id text,
  p_reason text,
  p_disputed_amount text,
  p_currency text,
  p_core_json jsonb,
  p_core_sha256 text,
  p_source text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_inserted bigint;
  v_existing_sha256 text;
begin
  insert into public.proofshield_cases (
    dispute_id, payment_id, order_id, reason, disputed_amount,
    currency, core_json, core_sha256, source
  ) values (
    p_dispute_id, p_payment_id, p_order_id, p_reason, p_disputed_amount::numeric,
    p_currency, p_core_json, p_core_sha256, p_source
  )
  on conflict (dispute_id) do nothing;

  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    insert into public.proofshield_case_history (dispute_id, action, detail)
    values (p_dispute_id, 'CASE_CREATED', format('Case created from %s.', p_source));
    return 'CREATED';
  end if;

  select core_sha256 into v_existing_sha256
  from public.proofshield_cases
  where dispute_id = p_dispute_id;

  if v_existing_sha256 = p_core_sha256 then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

create or replace function public.proofshield_list_cases()
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
  group by c.dispute_id
  order by c.updated_at desc, c.dispute_id;
$$;

create or replace function public.proofshield_register_evidence_file(
  p_dispute_id text,
  p_file_id text,
  p_original_name text,
  p_content_type text,
  p_size_bytes bigint,
  p_sha256 text,
  p_storage_key text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.proofshield_cases where dispute_id = p_dispute_id
  ) then
    return 'CASE_NOT_FOUND';
  end if;

  insert into public.proofshield_evidence_files (
    file_id, dispute_id, original_name, content_type, size_bytes, sha256, storage_key
  ) values (
    p_file_id, p_dispute_id, p_original_name, p_content_type, p_size_bytes, p_sha256, p_storage_key
  )
  on conflict do nothing;

  if not found then
    return 'CONFLICT';
  end if;

  update public.proofshield_cases set updated_at = now() where dispute_id = p_dispute_id;
  insert into public.proofshield_case_history (
    dispute_id, action, reference_id, detail
  ) values (
    p_dispute_id,
    'FILE_UPLOADED',
    p_file_id,
    format('Evidence file uploaded; content_type=%s; size_bytes=%s.', p_content_type, p_size_bytes)
  );
  return 'CREATED';
end;
$$;

create or replace function public.proofshield_add_evidence(
  p_dispute_id text,
  p_evidence_id text,
  p_document_json jsonb,
  p_document_sha256 text,
  p_evidence_type text,
  p_source_verified boolean
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_inserted bigint;
  v_existing_dispute_id text;
  v_existing_sha256 text;
begin
  if not exists (
    select 1 from public.proofshield_cases where dispute_id = p_dispute_id
  ) then
    return 'CASE_NOT_FOUND';
  end if;

  insert into public.proofshield_evidence (
    evidence_id, dispute_id, document_json, document_sha256
  ) values (
    p_evidence_id, p_dispute_id, p_document_json, p_document_sha256
  )
  on conflict (evidence_id) do nothing;

  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    update public.proofshield_cases set updated_at = now() where dispute_id = p_dispute_id;
    insert into public.proofshield_case_history (
      dispute_id, action, reference_id, detail
    ) values (
      p_dispute_id,
      'EVIDENCE_ADDED',
      p_evidence_id,
      format('%s evidence added; source_verified=%s.', p_evidence_type, p_source_verified)
    );
    return 'ADDED';
  end if;

  select dispute_id, document_sha256
  into v_existing_dispute_id, v_existing_sha256
  from public.proofshield_evidence
  where evidence_id = p_evidence_id;

  if v_existing_dispute_id = p_dispute_id and v_existing_sha256 = p_document_sha256 then
    return 'EXISTS';
  end if;
  return 'CONFLICT';
end;
$$;

create or replace function public.proofshield_record_assessment(
  p_dispute_id text,
  p_decision text,
  p_evidence_score double precision
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.proofshield_cases where dispute_id = p_dispute_id
  ) then
    return 'CASE_NOT_FOUND';
  end if;
  insert into public.proofshield_case_history (
    dispute_id, action, detail
  ) values (
    p_dispute_id,
    'ASSESSED',
    format('Decision=%s; evidence_score=%s.', p_decision, round(p_evidence_score::numeric, 4))
  );
  return 'RECORDED';
end;
$$;

create or replace function public.proofshield_claim_webhook_event(
  p_event_id text,
  p_body_sha256 text,
  p_event_type text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_inserted bigint;
  v_existing_sha256 text;
  v_existing_status text;
begin
  insert into public.proofshield_webhook_events (
    event_id, body_sha256, event_type, status, detail
  ) values (
    p_event_id,
    p_body_sha256,
    p_event_type,
    'RECEIVED',
    'Signature verified and event accepted for processing.'
  )
  on conflict (event_id) do nothing;

  get diagnostics v_inserted = row_count;
  if v_inserted = 1 then
    insert into public.proofshield_webhook_audit (
      event_id, body_sha256, status, event_type, detail
    ) values (
      p_event_id,
      p_body_sha256,
      'RECEIVED',
      p_event_type,
      'Signature verified and event accepted for processing.'
    );
    return 'CLAIMED';
  end if;

  select body_sha256, status
  into v_existing_sha256, v_existing_status
  from public.proofshield_webhook_events
  where event_id = p_event_id
  for update;

  if v_existing_sha256 <> p_body_sha256 then
    insert into public.proofshield_webhook_audit (
      event_id, body_sha256, status, event_type, detail
    ) values (
      p_event_id,
      p_body_sha256,
      'REJECTED',
      p_event_type,
      'Event ID was reused with a different signed body.'
    );
    return 'CONFLICT';
  end if;

  if v_existing_status <> 'FAILED' then
    insert into public.proofshield_webhook_audit (
      event_id, body_sha256, status, event_type, detail
    ) values (
      p_event_id,
      p_body_sha256,
      'DUPLICATE',
      p_event_type,
      'Duplicate event was acknowledged without reprocessing.'
    );
    return 'DUPLICATE';
  end if;

  update public.proofshield_webhook_events
  set status = 'RECEIVED', event_type = p_event_type,
      detail = 'Previously failed event accepted for retry.', updated_at = now()
  where event_id = p_event_id;
  insert into public.proofshield_webhook_audit (
    event_id, body_sha256, status, event_type, detail
  ) values (
    p_event_id,
    p_body_sha256,
    'RECEIVED',
    p_event_type,
    'Previously failed event accepted for retry.'
  );
  return 'CLAIMED';
end;
$$;

create or replace function public.proofshield_finish_webhook_event(
  p_event_id text,
  p_body_sha256 text,
  p_status text,
  p_detail text,
  p_event_type text,
  p_dispute_id text,
  p_decision text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_updated bigint;
begin
  if p_status not in ('PROCESSED', 'IGNORED', 'NEEDS_ENRICHMENT') then
    return 'INVALID';
  end if;
  update public.proofshield_webhook_events
  set status = p_status,
      event_type = coalesce(p_event_type, event_type),
      dispute_id = p_dispute_id,
      decision = p_decision,
      detail = p_detail,
      updated_at = now()
  where event_id = p_event_id
    and body_sha256 = p_body_sha256
    and status = 'RECEIVED';
  get diagnostics v_updated = row_count;
  if v_updated <> 1 then
    return 'INVALID';
  end if;
  insert into public.proofshield_webhook_audit (
    event_id, body_sha256, status, event_type, dispute_id, decision, detail
  ) values (
    p_event_id, p_body_sha256, p_status, p_event_type, p_dispute_id, p_decision, p_detail
  );
  return 'RECORDED';
end;
$$;

create or replace function public.proofshield_fail_webhook_event(
  p_event_id text,
  p_body_sha256 text,
  p_event_type text,
  p_detail text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
declare
  v_updated bigint;
begin
  update public.proofshield_webhook_events
  set status = 'FAILED', event_type = coalesce(p_event_type, event_type),
      detail = p_detail, updated_at = now()
  where event_id = p_event_id and body_sha256 = p_body_sha256;
  get diagnostics v_updated = row_count;
  insert into public.proofshield_webhook_audit (
    event_id, body_sha256, status, event_type, detail
  ) values (
    p_event_id, p_body_sha256, 'FAILED', p_event_type, p_detail
  );
  if v_updated = 1 then
    return 'RECORDED';
  end if;
  return 'AUDITED';
end;
$$;

create or replace function public.proofshield_reject_webhook_event(
  p_event_id text,
  p_body_sha256 text,
  p_detail text
)
returns text
language plpgsql
security invoker
set search_path = ''
as $$
begin
  insert into public.proofshield_webhook_audit (
    event_id, body_sha256, status, detail
  ) values (
    p_event_id, p_body_sha256, 'REJECTED', p_detail
  );
  return 'RECORDED';
end;
$$;

revoke execute on function public.proofshield_save_case(text, text, text, text, text, text, jsonb, text, text)
  from public, anon, authenticated;
revoke execute on function public.proofshield_list_cases()
  from public, anon, authenticated;
revoke execute on function public.proofshield_register_evidence_file(text, text, text, text, bigint, text, text)
  from public, anon, authenticated;
revoke execute on function public.proofshield_add_evidence(text, text, jsonb, text, text, boolean)
  from public, anon, authenticated;
revoke execute on function public.proofshield_record_assessment(text, text, double precision)
  from public, anon, authenticated;
revoke execute on function public.proofshield_claim_webhook_event(text, text, text)
  from public, anon, authenticated;
revoke execute on function public.proofshield_finish_webhook_event(text, text, text, text, text, text, text)
  from public, anon, authenticated;
revoke execute on function public.proofshield_fail_webhook_event(text, text, text, text)
  from public, anon, authenticated;
revoke execute on function public.proofshield_reject_webhook_event(text, text, text)
  from public, anon, authenticated;

grant execute on function public.proofshield_save_case(text, text, text, text, text, text, jsonb, text, text)
  to service_role;
grant execute on function public.proofshield_list_cases()
  to service_role;
grant execute on function public.proofshield_register_evidence_file(text, text, text, text, bigint, text, text)
  to service_role;
grant execute on function public.proofshield_add_evidence(text, text, jsonb, text, text, boolean)
  to service_role;
grant execute on function public.proofshield_record_assessment(text, text, double precision)
  to service_role;
grant execute on function public.proofshield_claim_webhook_event(text, text, text)
  to service_role;
grant execute on function public.proofshield_finish_webhook_event(text, text, text, text, text, text, text)
  to service_role;
grant execute on function public.proofshield_fail_webhook_event(text, text, text, text)
  to service_role;
grant execute on function public.proofshield_reject_webhook_event(text, text, text)
  to service_role;

insert into storage.buckets (
  id, name, public, file_size_limit, allowed_mime_types
)
values (
  'proofshield-evidence',
  'proofshield-evidence',
  false,
  5000000,
  array['application/json', 'application/pdf', 'image/jpeg', 'image/png', 'text/plain']::text[]
)
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
