"""Content-addressed storage for small local evidence files."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

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


@dataclass(frozen=True)
class StoredFileBlob:
    storage_key: str
    sha256: str
    size_bytes: int


def safe_original_name(value: str | None) -> str:
    if value is None:
        return "evidence"
    name = Path(value).name.strip()
    if not name or name in {".", ".."}:
        return "evidence"
    return name[:255]


class LocalEvidenceFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, content: bytes, *, content_type: str | None) -> StoredFileBlob:
        normalized_content_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if normalized_content_type not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedEvidenceFile(
                f"unsupported evidence content type: {normalized_content_type or 'missing'}"
            )
        if not content:
            raise EvidenceFileError("evidence file must not be empty")
        if len(content) > MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceFileTooLarge(
                f"evidence file exceeds {MAX_EVIDENCE_FILE_BYTES} bytes"
            )
        self._validate_content(content, normalized_content_type)

        digest = hashlib.sha256(content).hexdigest()
        final_path = self.root / digest
        if not final_path.exists():
            temporary_path = self.root / f".{uuid4().hex}.tmp"
            try:
                with temporary_path.open("xb") as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, final_path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return StoredFileBlob(
            storage_key=digest,
            sha256=digest,
            size_bytes=len(content),
        )

    @staticmethod
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
