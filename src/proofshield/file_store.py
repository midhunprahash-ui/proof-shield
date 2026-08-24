"""Evidence-file validation and private Supabase Storage persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/plain",
}
MAX_EVIDENCE_FILE_BYTES = 5_000_000


class EvidenceFileError(ValueError):
    pass


class UnsupportedEvidenceFile(EvidenceFileError):
    pass


class EvidenceFileTooLarge(EvidenceFileError):
    pass


class MalformedEvidenceFile(EvidenceFileError):
    pass


class EvidenceFileUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredFileBlob:
    storage_key: str
    sha256: str
    size_bytes: int


class EvidenceFileStore(Protocol):
    def save(
        self,
        content: bytes,
        *,
        content_type: str | None,
        dispute_id: str,
        file_id: str,
    ) -> StoredFileBlob: ...

    def delete(self, storage_key: str) -> None: ...

    def read(self, storage_key: str) -> bytes: ...


def safe_original_name(value: str | None) -> str:
    if value is None:
        return "evidence"
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        return "evidence"
    return name[:255]


def normalize_and_validate_file(
    content: bytes, content_type: str | None
) -> tuple[str, str]:
    normalized = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if normalized not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedEvidenceFile(
            f"unsupported evidence content type: {normalized or 'missing'}"
        )
    if not content:
        raise EvidenceFileError("evidence file must not be empty")
    if len(content) > MAX_EVIDENCE_FILE_BYTES:
        raise EvidenceFileTooLarge(
            f"evidence file exceeds {MAX_EVIDENCE_FILE_BYTES} bytes"
        )
    _validate_content(content, normalized)
    return normalized, hashlib.sha256(content).hexdigest()


def _validate_content(content: bytes, content_type: str) -> None:
    if content_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise MalformedEvidenceFile("file content does not match application/pdf")
    if content_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MalformedEvidenceFile("file content does not match image/png")
    if content_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise MalformedEvidenceFile("file content does not match image/jpeg")
    if content_type == "application/json":
        try:
            json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MalformedEvidenceFile("file content is not valid JSON") from error
    if content_type == "text/plain":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise MalformedEvidenceFile("text evidence is not valid UTF-8") from error


class SupabaseEvidenceFileStore:
    """Write evidence bytes only through the Supabase Storage API."""

    def __init__(self, client: Any, *, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def save(
        self,
        content: bytes,
        *,
        content_type: str | None,
        dispute_id: str,
        file_id: str,
    ) -> StoredFileBlob:
        normalized, digest = normalize_and_validate_file(content, content_type)
        case_key = hashlib.sha256(dispute_id.encode("utf-8")).hexdigest()
        storage_key = f"cases/{case_key}/{file_id}/{digest}"
        self.client.storage.from_(self.bucket).upload(
            path=storage_key,
            file=content,
            file_options={
                "content-type": normalized,
                "cache-control": "3600",
                "upsert": "false",
            },
        )
        return StoredFileBlob(
            storage_key=storage_key,
            sha256=digest,
            size_bytes=len(content),
        )

    def delete(self, storage_key: str) -> None:
        self.client.storage.from_(self.bucket).remove([storage_key])

    def read(self, storage_key: str) -> bytes:
        try:
            return self.client.storage.from_(self.bucket).download(storage_key)
        except Exception as error:
            raise EvidenceFileUnavailable(
                "a cited evidence file could not be read from private storage"
            ) from error
