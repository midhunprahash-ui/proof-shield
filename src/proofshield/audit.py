"""Append-only local webhook audit log with idempotency protection."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import AwareDatetime, BaseModel, ConfigDict

from proofshield.domain import Decision


class AuditStatus(StrEnum):
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    NEEDS_ENRICHMENT = "NEEDS_ENRICHMENT"


class ClaimResult(StrEnum):
    CLAIMED = "CLAIMED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


class AuditEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    body_sha256: str
    status: AuditStatus
    recorded_at: AwareDatetime
    event_type: str | None = None
    dispute_id: str | None = None
    decision: Decision | None = None
    detail: str


class LocalEventLedger:
    """Track accepted event IDs and keep an append-only JSONL history.

    Completed events survive restarts. Incomplete or failed events can be retried,
    while concurrent duplicates are rejected inside the current process.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._completed: dict[str, str] = {}
        self._active: dict[str, str] = {}
        self._load_completed_events()

    def _load_completed_events(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    entry = AuditEntry.model_validate_json(line)
                except ValueError as error:
                    raise ValueError(
                        f"invalid audit entry at {self.path}:{line_number}"
                    ) from error
                if entry.status in {
                    AuditStatus.PROCESSED,
                    AuditStatus.IGNORED,
                    AuditStatus.NEEDS_ENRICHMENT,
                }:
                    existing_digest = self._completed.get(entry.event_id)
                    if existing_digest is not None and existing_digest != entry.body_sha256:
                        raise ValueError(
                            f"conflicting completed event ID in audit log: {entry.event_id}"
                        )
                    self._completed[entry.event_id] = entry.body_sha256

    def claim(self, event_id: str, digest: str, *, event_type: str | None) -> ClaimResult:
        with self._lock:
            existing_digest = self._completed.get(event_id) or self._active.get(event_id)
            if existing_digest is not None:
                status = (
                    AuditStatus.DUPLICATE
                    if existing_digest == digest
                    else AuditStatus.REJECTED
                )
                self._append_unlocked(
                    AuditEntry(
                        event_id=event_id,
                        body_sha256=digest,
                        status=status,
                        recorded_at=datetime.now(UTC),
                        event_type=event_type,
                        detail=(
                            "Duplicate event was acknowledged without reprocessing."
                            if status == AuditStatus.DUPLICATE
                            else "Event ID was reused with a different signed body."
                        ),
                    )
                )
                return (
                    ClaimResult.DUPLICATE
                    if status == AuditStatus.DUPLICATE
                    else ClaimResult.CONFLICT
                )

            self._active[event_id] = digest
            self._append_unlocked(
                AuditEntry(
                    event_id=event_id,
                    body_sha256=digest,
                    status=AuditStatus.RECEIVED,
                    recorded_at=datetime.now(UTC),
                    event_type=event_type,
                    detail="Signature verified and event accepted for local processing.",
                )
            )
            return ClaimResult.CLAIMED

    def finish(
        self,
        event_id: str,
        digest: str,
        *,
        status: AuditStatus,
        detail: str,
        event_type: str | None = None,
        dispute_id: str | None = None,
        decision: Decision | None = None,
    ) -> None:
        if status not in {
            AuditStatus.PROCESSED,
            AuditStatus.IGNORED,
            AuditStatus.NEEDS_ENRICHMENT,
        }:
            raise ValueError("finish status must describe a completed event")
        with self._lock:
            if self._active.get(event_id) != digest:
                raise ValueError("event was not claimed with this body digest")
            self._active.pop(event_id)
            self._completed[event_id] = digest
            self._append_unlocked(
                AuditEntry(
                    event_id=event_id,
                    body_sha256=digest,
                    status=status,
                    recorded_at=datetime.now(UTC),
                    event_type=event_type,
                    dispute_id=dispute_id,
                    decision=decision,
                    detail=detail,
                )
            )

    def fail(
        self,
        event_id: str,
        digest: str,
        *,
        detail: str,
        event_type: str | None = None,
    ) -> None:
        with self._lock:
            self._active.pop(event_id, None)
            self._append_unlocked(
                AuditEntry(
                    event_id=event_id,
                    body_sha256=digest,
                    status=AuditStatus.FAILED,
                    recorded_at=datetime.now(UTC),
                    event_type=event_type,
                    detail=detail,
                )
            )

    def reject_untrusted(
        self,
        event_id: str,
        digest: str,
        *,
        detail: str,
    ) -> None:
        """Audit a rejection without reserving an attacker-controlled event ID."""

        with self._lock:
            self._append_unlocked(
                AuditEntry(
                    event_id=event_id,
                    body_sha256=digest,
                    status=AuditStatus.REJECTED,
                    recorded_at=datetime.now(UTC),
                    detail=detail,
                )
            )

    def entries(self) -> list[AuditEntry]:
        if not self.path.exists():
            return []
        with self._lock, self.path.open("r", encoding="utf-8") as handle:
            return [AuditEntry.model_validate_json(line) for line in handle if line.strip()]

    def _append_unlocked(self, entry: AuditEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(entry.model_dump_json() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
