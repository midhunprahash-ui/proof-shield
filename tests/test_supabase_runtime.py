from __future__ import annotations

import base64
import json

import pytest

from proofshield.file_store import SupabaseEvidenceFileStore
from proofshield.supabase_runtime import SupabaseConfigurationError, SupabaseSettings


def test_settings_accept_only_matching_backend_project(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "qoujhmqkjicvcwoiyqkp")
    monkeypatch.setenv(
        "SUPABASE_URL", "https://qoujhmqkjicvcwoiyqkp.supabase.co/"
    )
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")
    monkeypatch.setenv("SUPABASE_EVIDENCE_BUCKET", "proofshield-evidence")

    settings = SupabaseSettings.from_env()

    assert settings.url == "https://qoujhmqkjicvcwoiyqkp.supabase.co"
    assert settings.project_ref == "qoujhmqkjicvcwoiyqkp"


def test_settings_reject_wrong_project(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "qoujhmqkjicvcwoiyqkp")
    monkeypatch.setenv("SUPABASE_URL", "https://wrongproject.supabase.co")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_test_only")

    with pytest.raises(SupabaseConfigurationError, match="does not match"):
        SupabaseSettings.from_env()


def test_settings_reject_example_secret(monkeypatch) -> None:
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "qoujhmqkjicvcwoiyqkp")
    monkeypatch.setenv(
        "SUPABASE_URL", "https://qoujhmqkjicvcwoiyqkp.supabase.co"
    )
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "sb_secret_replace_me")

    with pytest.raises(SupabaseConfigurationError, match="placeholder"):
        SupabaseSettings.from_env()


@pytest.mark.parametrize("key", ["sb_publishable_test", "legacy_anon_jwt"])
def test_settings_reject_public_keys(monkeypatch, key: str) -> None:
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "qoujhmqkjicvcwoiyqkp")
    monkeypatch.setenv(
        "SUPABASE_URL", "https://qoujhmqkjicvcwoiyqkp.supabase.co"
    )
    monkeypatch.setenv(
        "SUPABASE_SECRET_KEY", _jwt_with_role("anon") if key == "legacy_anon_jwt" else key
    )

    with pytest.raises(SupabaseConfigurationError, match="public key"):
        SupabaseSettings.from_env()


def test_storage_uses_private_case_isolated_server_key() -> None:
    client = FakeStorageClient()
    store = SupabaseEvidenceFileStore(client, bucket="proofshield-evidence")

    blob = store.save(
        b"%PDF-1.4 synthetic",
        content_type="application/pdf",
        dispute_id="disp_1",
        file_id="file_1",
    )

    assert blob.storage_key.startswith("cases/")
    assert "/file_1/" in blob.storage_key
    assert "disp_1" not in blob.storage_key
    assert client.bucket_name == "proofshield-evidence"
    assert client.uploaded["path"] == blob.storage_key
    assert client.uploaded["file_options"] == {
        "content-type": "application/pdf",
        "cache-control": "3600",
        "upsert": "false",
    }


def _jwt_with_role(role: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"role": role}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


class FakeStorageClient:
    def __init__(self) -> None:
        self.storage = self
        self.bucket_name: str | None = None
        self.uploaded: dict = {}

    def from_(self, bucket: str) -> FakeStorageClient:
        self.bucket_name = bucket
        return self

    def upload(self, **values) -> None:
        self.uploaded = values

    def remove(self, paths: list[str]) -> None:
        self.removed = paths
