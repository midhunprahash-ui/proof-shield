from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/20260823160507_proofshield_supabase_foundation.sql"
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
