"""Webhook audit contracts and the Supabase-backed event ledger."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

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


class EventLedger(Protocol):
    def claim(
        self, event_id: str, digest: str, *, event_type: str | None
    ) -> ClaimResult: ...

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
    ) -> None: ...

    def fail(
        self,
        event_id: str,
        digest: str,
        *,
        detail: str,
        event_type: str | None = None,
    ) -> None: ...

    def reject_untrusted(self, event_id: str, digest: str, *, detail: str) -> None: ...

    def entries(self) -> list[AuditEntry]: ...


def _rpc_scalar(client: Any, function: str, parameters: dict[str, Any]) -> str:
    data = client.rpc(function, parameters).execute().data
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        value = data.get(function) or data.get("status")
        if isinstance(value, str):
            return value
    if isinstance(data, list) and len(data) == 1:
        item = data[0]
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            value = item.get(function) or item.get("status")
            if isinstance(value, str):
                return value
    raise RuntimeError(f"Supabase RPC {function} returned an unexpected response")


class SupabaseEventLedger:
    """Use Postgres transactions for durable cross-process webhook idempotency."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def claim(self, event_id: str, digest: str, *, event_type: str | None) -> ClaimResult:
        result = _rpc_scalar(
            self.client,
            "proofshield_claim_webhook_event",
            {
                "p_event_id": event_id,
                "p_body_sha256": digest,
                "p_event_type": event_type,
            },
        )
        try:
            return ClaimResult(result)
        except ValueError as error:
            raise RuntimeError(f"unexpected webhook claim status: {result}") from error

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
        result = _rpc_scalar(
            self.client,
            "proofshield_finish_webhook_event",
            {
                "p_event_id": event_id,
                "p_body_sha256": digest,
                "p_status": str(status),
                "p_detail": detail,
                "p_event_type": event_type,
                "p_dispute_id": dispute_id,
                "p_decision": str(decision) if decision is not None else None,
            },
        )
        if result != "RECORDED":
            raise ValueError("event was not claimed with this body digest")

    def fail(
        self,
        event_id: str,
        digest: str,
        *,
        detail: str,
        event_type: str | None = None,
    ) -> None:
        _rpc_scalar(
            self.client,
            "proofshield_fail_webhook_event",
            {
                "p_event_id": event_id,
                "p_body_sha256": digest,
                "p_event_type": event_type,
                "p_detail": detail,
            },
        )

    def reject_untrusted(self, event_id: str, digest: str, *, detail: str) -> None:
        _rpc_scalar(
            self.client,
            "proofshield_reject_webhook_event",
            {
                "p_event_id": event_id,
                "p_body_sha256": digest,
                "p_detail": detail,
            },
        )

    def entries(self) -> list[AuditEntry]:
        rows = (
            self.client.table("proofshield_webhook_audit")
            .select(
                "event_id,body_sha256,status,recorded_at,event_type,"
                "dispute_id,decision,detail"
            )
            .order("sequence")
            .execute()
            .data
        )
        return [AuditEntry.model_validate(row) for row in rows]
