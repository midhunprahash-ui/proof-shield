"""Transactional local SQLite storage for cases, evidence, and case history."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel

from proofshield.domain import Assessment, DisputeCase, EvidenceDocument


class CaseStoreError(RuntimeError):
    """Base class for local case-storage errors."""


class CaseNotFoundError(CaseStoreError):
    pass


class CaseConflictError(CaseStoreError):
    pass


class EvidenceConflictError(CaseStoreError):
    pass


class CaseHistoryAction(StrEnum):
    CASE_CREATED = "CASE_CREATED"
    FILE_UPLOADED = "FILE_UPLOADED"
    EVIDENCE_ADDED = "EVIDENCE_ADDED"
    ASSESSED = "ASSESSED"


class CaseSummary(BaseModel):
    dispute_id: str
    payment_id: str
    order_id: str
    reason: str
    disputed_amount: str
    currency: str
    evidence_count: int
    updated_at: AwareDatetime


class CaseHistoryEntry(BaseModel):
    sequence: int
    dispute_id: str
    action: CaseHistoryAction
    reference_id: str | None
    recorded_at: AwareDatetime
    detail: str


class EvidenceFileMetadata(BaseModel):
    file_id: str
    dispute_id: str
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: AwareDatetime


def _canonical_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocalCaseRepository:
    """Store trusted local case data without silently overwriting conflicts."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._schema_lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._schema_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS cases (
                        dispute_id TEXT PRIMARY KEY,
                        payment_id TEXT NOT NULL,
                        order_id TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        disputed_amount TEXT NOT NULL,
                        currency TEXT NOT NULL,
                        core_json TEXT NOT NULL,
                        core_sha256 TEXT NOT NULL,
                        source TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS evidence (
                        evidence_id TEXT PRIMARY KEY,
                        dispute_id TEXT NOT NULL,
                        document_json TEXT NOT NULL,
                        document_sha256 TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (dispute_id) REFERENCES cases(dispute_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_evidence_dispute_id
                    ON evidence(dispute_id);

                    CREATE TABLE IF NOT EXISTS evidence_files (
                        file_id TEXT PRIMARY KEY,
                        dispute_id TEXT NOT NULL,
                        original_name TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        sha256 TEXT NOT NULL,
                        storage_key TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (dispute_id) REFERENCES cases(dispute_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_evidence_files_dispute_id
                    ON evidence_files(dispute_id);

                    CREATE TABLE IF NOT EXISTS case_history (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        dispute_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        reference_id TEXT,
                        recorded_at TEXT NOT NULL,
                        detail TEXT NOT NULL,
                        FOREIGN KEY (dispute_id) REFERENCES cases(dispute_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_case_history_dispute_id
                    ON case_history(dispute_id, sequence);
                    """
                )

    def save_case(self, case: DisputeCase, *, source: str) -> bool:
        core_case = case.model_copy(update={"evidence": []})
        core_json = _canonical_json(core_case)
        core_digest = _sha256(core_json)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT core_sha256 FROM cases WHERE dispute_id = ?", (case.dispute_id,)
            ).fetchone()
            if existing is not None:
                if existing["core_sha256"] != core_digest:
                    raise CaseConflictError(
                        f"case {case.dispute_id} already exists with different core facts"
                    )
                return False

            connection.execute(
                """
                INSERT INTO cases (
                    dispute_id, payment_id, order_id, reason, disputed_amount,
                    currency, core_json, core_sha256, source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.dispute_id,
                    case.payment_id,
                    case.order_id,
                    case.reason,
                    str(case.disputed_amount),
                    case.currency,
                    core_json,
                    core_digest,
                    source,
                    now,
                    now,
                ),
            )
            self._append_history(
                connection,
                dispute_id=case.dispute_id,
                action=CaseHistoryAction.CASE_CREATED,
                reference_id=None,
                detail=f"Case created from {source}.",
                recorded_at=now,
            )
        return True

    def get_case(self, dispute_id: str) -> DisputeCase:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT core_json FROM cases WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
            if row is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            evidence_rows = connection.execute(
                """
                SELECT document_json FROM evidence
                WHERE dispute_id = ? ORDER BY created_at, evidence_id
                """,
                (dispute_id,),
            ).fetchall()

        case = DisputeCase.model_validate_json(row["core_json"])
        evidence = [
            EvidenceDocument.model_validate_json(evidence_row["document_json"])
            for evidence_row in evidence_rows
        ]
        return case.model_copy(update={"evidence": evidence})

    def list_cases(self) -> list[CaseSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.dispute_id, c.payment_id, c.order_id, c.reason,
                       c.disputed_amount, c.currency, c.updated_at,
                       COUNT(e.evidence_id) AS evidence_count
                FROM cases c
                LEFT JOIN evidence e ON e.dispute_id = c.dispute_id
                GROUP BY c.dispute_id
                ORDER BY c.updated_at DESC, c.dispute_id
                """
            ).fetchall()
        return [
            CaseSummary(
                dispute_id=row["dispute_id"],
                payment_id=row["payment_id"],
                order_id=row["order_id"],
                reason=row["reason"],
                disputed_amount=row["disputed_amount"],
                currency=row["currency"],
                evidence_count=row["evidence_count"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def register_evidence_file(
        self,
        dispute_id: str,
        *,
        original_name: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        storage_key: str,
    ) -> EvidenceFileMetadata:
        file_id = f"file_{uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            case_exists = connection.execute(
                "SELECT 1 FROM cases WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
            if case_exists is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            connection.execute(
                """
                INSERT INTO evidence_files (
                    file_id, dispute_id, original_name, content_type,
                    size_bytes, sha256, storage_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id,
                    dispute_id,
                    original_name,
                    content_type,
                    size_bytes,
                    sha256,
                    storage_key,
                    now,
                ),
            )
            connection.execute(
                "UPDATE cases SET updated_at = ? WHERE dispute_id = ?",
                (now, dispute_id),
            )
            self._append_history(
                connection,
                dispute_id=dispute_id,
                action=CaseHistoryAction.FILE_UPLOADED,
                reference_id=file_id,
                detail=(
                    f"Evidence file uploaded; content_type={content_type}; "
                    f"size_bytes={size_bytes}."
                ),
                recorded_at=now,
            )
        return EvidenceFileMetadata(
            file_id=file_id,
            dispute_id=dispute_id,
            original_name=original_name,
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            created_at=now,
        )

    def get_evidence_file(
        self, dispute_id: str, file_id: str
    ) -> EvidenceFileMetadata:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT file_id, dispute_id, original_name, content_type,
                       size_bytes, sha256, created_at
                FROM evidence_files
                WHERE file_id = ? AND dispute_id = ?
                """,
                (file_id, dispute_id),
            ).fetchone()
        if row is None:
            raise CaseNotFoundError(
                f"evidence file {file_id} was not found for case {dispute_id}"
            )
        return EvidenceFileMetadata.model_validate(dict(row))

    def list_evidence_files(self, dispute_id: str) -> list[EvidenceFileMetadata]:
        with self._connect() as connection:
            case_exists = connection.execute(
                "SELECT 1 FROM cases WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
            if case_exists is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            rows = connection.execute(
                """
                SELECT file_id, dispute_id, original_name, content_type,
                       size_bytes, sha256, created_at
                FROM evidence_files
                WHERE dispute_id = ? ORDER BY created_at, file_id
                """,
                (dispute_id,),
            ).fetchall()
        return [EvidenceFileMetadata.model_validate(dict(row)) for row in rows]

    def add_evidence(self, dispute_id: str, document: EvidenceDocument) -> bool:
        document_json = _canonical_json(document)
        document_digest = _sha256(document_json)
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            case_exists = connection.execute(
                "SELECT 1 FROM cases WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
            if case_exists is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")

            existing = connection.execute(
                """
                SELECT dispute_id, document_sha256 FROM evidence
                WHERE evidence_id = ?
                """,
                (document.evidence_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["dispute_id"] == dispute_id
                    and existing["document_sha256"] == document_digest
                ):
                    return False
                raise EvidenceConflictError(
                    f"evidence ID {document.evidence_id} is already attached elsewhere"
                )

            connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id, dispute_id, document_json, document_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    document.evidence_id,
                    dispute_id,
                    document_json,
                    document_digest,
                    now,
                ),
            )
            connection.execute(
                "UPDATE cases SET updated_at = ? WHERE dispute_id = ?",
                (now, dispute_id),
            )
            self._append_history(
                connection,
                dispute_id=dispute_id,
                action=CaseHistoryAction.EVIDENCE_ADDED,
                reference_id=document.evidence_id,
                detail=(
                    f"{document.evidence_type} evidence added; "
                    f"source_verified={document.source_verified}."
                ),
                recorded_at=now,
            )
        return True

    def record_assessment(self, assessment: Assessment) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            case_exists = connection.execute(
                "SELECT 1 FROM cases WHERE dispute_id = ?", (assessment.dispute_id,)
            ).fetchone()
            if case_exists is None:
                raise CaseNotFoundError(f"case {assessment.dispute_id} was not found")
            self._append_history(
                connection,
                dispute_id=assessment.dispute_id,
                action=CaseHistoryAction.ASSESSED,
                reference_id=None,
                detail=(
                    f"Decision={assessment.decision}; "
                    f"evidence_score={assessment.evidence_score:.4f}."
                ),
                recorded_at=now,
            )

    def get_history(self, dispute_id: str) -> list[CaseHistoryEntry]:
        with self._connect() as connection:
            case_exists = connection.execute(
                "SELECT 1 FROM cases WHERE dispute_id = ?", (dispute_id,)
            ).fetchone()
            if case_exists is None:
                raise CaseNotFoundError(f"case {dispute_id} was not found")
            rows = connection.execute(
                """
                SELECT sequence, dispute_id, action, reference_id, recorded_at, detail
                FROM case_history WHERE dispute_id = ? ORDER BY sequence
                """,
                (dispute_id,),
            ).fetchall()
        return [CaseHistoryEntry.model_validate(dict(row)) for row in rows]

    @staticmethod
    def _append_history(
        connection: sqlite3.Connection,
        *,
        dispute_id: str,
        action: CaseHistoryAction,
        reference_id: str | None,
        detail: str,
        recorded_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO case_history (
                dispute_id, action, reference_id, recorded_at, detail
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (dispute_id, action, reference_id, recorded_at, detail),
        )
