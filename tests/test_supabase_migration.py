from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/20260823160507_proofshield_supabase_foundation.sql"
)
DRAFT_MIGRATION = Path(
    "supabase/migrations/20260823170424_response_drafts.sql"
)
REVIEW_MIGRATION = Path(
    "supabase/migrations/20260824070552_draft_reviews_and_evidence_packets.sql"
)
AUTH_MIGRATION = Path(
    "supabase/migrations/20260826080225_operator_auth_and_ownership.sql"
)
RESOLUTION_MIGRATION = Path(
    "supabase/migrations/20260826104022_evidence_resolution.sql"
)
RESOLUTION_INDEX_MIGRATION = Path(
    "supabase/migrations/20260826110406_evidence_resolution_fk_indexes.sql"
)
TABLES = {
    "proofshield_cases",
    "proofshield_evidence",
    "proofshield_evidence_files",
    "proofshield_case_history",
    "proofshield_webhook_events",
    "proofshield_webhook_audit",
}


def test_every_proofshield_table_enables_rls() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for table in TABLES:
        assert f"alter table public.{table} enable row level security;" in sql
        assert f"revoke all on table public.{table} from anon, authenticated" in sql


def test_storage_bucket_is_private_and_restricted() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "'proofshield-evidence'" in sql
    assert "false," in sql
    assert "5000000" in sql
    assert "allowed_mime_types" in sql


def test_rpc_functions_are_not_executable_by_browser_roles() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for function in {
        "proofshield_save_case",
        "proofshield_add_evidence",
        "proofshield_claim_webhook_event",
        "proofshield_finish_webhook_event",
    }:
        revoke_position = sql.index(f"revoke execute on function public.{function}")
        statement_end = sql.index(";", revoke_position)
        statement = sql[revoke_position:statement_end]
        assert "public, anon, authenticated" in statement


def test_existing_rls_trigger_function_is_not_browser_callable() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert (
        "revoke execute on function public.rls_auto_enable() "
        "from public, anon, authenticated;"
    ) in sql


def test_response_drafts_are_backend_only_and_human_approved() -> None:
    sql = DRAFT_MIGRATION.read_text(encoding="utf-8")

    assert "create table public.proofshield_response_drafts" in sql
    assert (
        "alter table public.proofshield_response_drafts enable row level security;"
        in sql
    )
    assert "from anon, authenticated, service_role;" in sql
    assert "grant select, insert" in sql
    assert "PENDING_HUMAN_APPROVAL" in sql
    assert "DRAFT_CREATED" in sql
    assert "security invoker" in sql
    assert "from public, anon, authenticated;" in sql
    assert "proofshield_response_drafts_dispute_id_idx" in sql


def test_draft_reviews_are_immutable_backend_only_decisions() -> None:
    sql = REVIEW_MIGRATION.read_text(encoding="utf-8")

    assert "create table public.proofshield_draft_reviews" in sql
    assert "primary key" in sql
    assert "references public.proofshield_response_drafts" in sql
    assert "alter table public.proofshield_draft_reviews enable row level security;" in sql
    assert "from anon, authenticated, service_role;" in sql
    assert "grant select, insert" in sql
    assert "DRAFT_APPROVED" in sql
    assert "DRAFT_REJECTED" in sql
    assert "on conflict (draft_id) do nothing" in sql
    assert "security invoker" in sql
    assert "from public, anon, authenticated;" in sql


def test_operator_auth_migration_uses_named_identity_and_owned_rows() -> None:
    sql = AUTH_MIGRATION.read_text(encoding="utf-8")

    assert "create table public.proofshield_operators" in sql
    assert "user_id uuid primary key references auth.users(id)" in sql
    assert "add column owner_id uuid" in sql
    assert "add column reviewer_user_id uuid" in sql
    assert "proofshield_cases_owner_updated_idx" in sql
    assert "proofshield_draft_reviews_reviewer_user_idx" in sql
    assert "to authenticated" in sql
    assert "owner_id = (select auth.uid())" in sql
    assert "reviewer_user_id" in sql
    assert "CASE_CLAIMED" in sql
    assert "proofshield_list_unassigned_cases" in sql
    assert "proofshield_claim_case" in sql


def test_operator_rls_helper_is_private_pinned_and_browser_read_only() -> None:
    sql = AUTH_MIGRATION.read_text(encoding="utf-8")

    assert "function private.proofshield_operator_owns_case" in sql
    assert "security definer" in sql
    assert "set search_path = ''" in sql
    assert "revoke execute" in sql
    assert "from public, anon;" in sql
    assert "grant select on table public.proofshield_cases to authenticated;" in sql
    assert "grant insert on table public.proofshield_cases to authenticated" not in sql
    assert "grant update on table public.proofshield_cases to authenticated" not in sql
    assert "grant delete on table public.proofshield_cases to authenticated" not in sql


def test_operator_mutation_rpcs_remain_service_role_only() -> None:
    sql = AUTH_MIGRATION.read_text(encoding="utf-8")

    for signature in {
        "proofshield_save_case(",
        "proofshield_list_cases(uuid)",
        "proofshield_list_unassigned_cases()",
        "proofshield_claim_case(text, uuid)",
        "proofshield_review_response_draft(",
    }:
        revoke_position = sql.index(f"revoke execute on function public.{signature}")
        statement_end = sql.index(";", revoke_position)
        statement = sql[revoke_position:statement_end]
        assert "public, anon, authenticated" in statement


def test_evidence_resolutions_are_append_only_owned_and_indexed() -> None:
    sql = RESOLUTION_MIGRATION.read_text(encoding="utf-8")

    assert "create table public.proofshield_evidence_resolutions" in sql
    assert "evidence_id text not null unique" in sql
    assert "on delete restrict" in sql
    assert "enable row level security" in sql
    assert "grant select, insert" in sql
    assert "grant select on table public.proofshield_evidence_resolutions" in sql
    assert "to authenticated" in sql
    assert "proofshield_operator_owns_case(dispute_id)" in sql
    assert "proofshield_evidence_resolutions_dispute_idx" in sql
    assert "proofshield_evidence_resolutions_replacement_idx" in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "EVIDENCE_RESOLVED" in sql


def test_resolution_rpc_is_service_only_and_database_validated() -> None:
    sql = RESOLUTION_MIGRATION.read_text(encoding="utf-8")

    assert "function public.proofshield_resolve_evidence" in sql
    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "replacement evidence must" not in sql
    assert "TYPE_MISMATCH" in sql
    assert "TARGET_IS_REPLACEMENT" in sql
    assert "REPLACEMENT_RESOLVED" in sql
    revoke_position = sql.index(
        "revoke execute on function public.proofshield_resolve_evidence"
    )
    statement_end = sql.index(";", revoke_position)
    assert "public, anon, authenticated" in sql[revoke_position:statement_end]


def test_resolution_composite_foreign_keys_have_covering_indexes() -> None:
    sql = RESOLUTION_INDEX_MIGRATION.read_text(encoding="utf-8")

    assert "proofshield_evidence_resolutions_source_case_idx" in sql
    assert "(evidence_id, dispute_id)" in sql
    assert "proofshield_evidence_resolutions_replacement_case_idx" in sql
    assert "replacement_evidence_id" in sql
    assert "dispute_id" in sql
