"""Fail-closed Supabase runtime configuration for the trusted backend."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from proofshield.audit import SupabaseEventLedger
from proofshield.case_store import SupabaseCaseRepository
from proofshield.file_store import SupabaseEvidenceFileStore


class SupabaseConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    secret_key: str
    project_ref: str
    evidence_bucket: str

    @classmethod
    def from_env(cls) -> SupabaseSettings:
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        secret_key = (
            os.getenv("SUPABASE_SECRET_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        project_ref = os.getenv("SUPABASE_PROJECT_REF", "").strip()
        bucket = os.getenv("SUPABASE_EVIDENCE_BUCKET", "proofshield-evidence").strip()
        missing = [
            name
            for name, value in {
                "SUPABASE_URL": url,
                "SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY)": secret_key,
                "SUPABASE_PROJECT_REF": project_ref,
                "SUPABASE_EVIDENCE_BUCKET": bucket,
            }.items()
            if not value
        ]
        if missing:
            raise SupabaseConfigurationError(
                "Missing backend Supabase configuration: " + ", ".join(missing)
            )

        parsed = urlparse(url)
        expected_host = f"{project_ref}.supabase.co"
        if parsed.scheme != "https" or parsed.hostname != expected_host:
            raise SupabaseConfigurationError(
                "SUPABASE_URL does not match SUPABASE_PROJECT_REF; refusing to connect"
            )
        if secret_key.startswith("sb_publishable_") or _jwt_role(secret_key) == "anon":
            raise SupabaseConfigurationError(
                "The backend requires a Supabase secret/service-role key, not a public key"
            )
        if "replace_me" in secret_key.lower():
            raise SupabaseConfigurationError(
                "SUPABASE_SECRET_KEY still contains the example placeholder"
            )
        return cls(
            url=url,
            secret_key=secret_key,
            project_ref=project_ref,
            evidence_bucket=bucket,
        )


@dataclass(frozen=True)
class SupabaseComponents:
    client: Any
    cases: SupabaseCaseRepository
    files: SupabaseEvidenceFileStore
    ledger: SupabaseEventLedger


def build_supabase_components(
    settings: SupabaseSettings | None = None,
) -> SupabaseComponents:
    configured = settings or SupabaseSettings.from_env()
    try:
        from supabase import create_client
    except ImportError as error:
        raise SupabaseConfigurationError(
            "The supabase Python package is not installed; install project dependencies"
        ) from error
    try:
        client = create_client(configured.url, configured.secret_key)
    except Exception as error:
        raise SupabaseConfigurationError(
            "The Supabase client could not be initialized from backend configuration"
        ) from error
    return SupabaseComponents(
        client=client,
        cases=SupabaseCaseRepository(client),
        files=SupabaseEvidenceFileStore(client, bucket=configured.evidence_bucket),
        ledger=SupabaseEventLedger(client),
    )


def _jwt_role(key: str) -> str | None:
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    role = decoded.get("role")
    return role if isinstance(role, str) else None
