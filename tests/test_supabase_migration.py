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
