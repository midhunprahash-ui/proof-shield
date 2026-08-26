"""Deterministic evidence-packet generation for approved response drafts."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from proofshield.case_store import EvidenceFileRecord
from proofshield.consistency import ConsistencyStatus, EvidenceConsistencyReport
from proofshield.domain import DisputeCase
from proofshield.drafting import ResponseDraft
from proofshield.reviewing import DraftReview, ReviewDecision

PACKET_FORMAT = "proofshield-evidence-packet-v2"


class EvidencePacketError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidencePacket:
    content: bytes
    sha256: str
    manifest_sha256: str


def build_evidence_packet(
    case: DisputeCase,
    draft: ResponseDraft,
    review: DraftReview,
    files: Iterable[tuple[EvidenceFileRecord, bytes]],
    consistency: EvidenceConsistencyReport,
) -> EvidencePacket:
    if draft.dispute_id != case.dispute_id or review.dispute_id != case.dispute_id:
        raise EvidencePacketError("case, draft, and review dispute IDs must match")
    if review.draft_id != draft.draft_id:
        raise EvidencePacketError("review does not belong to this draft")
    if review.decision != ReviewDecision.APPROVED:
        raise EvidencePacketError("only an approved draft can be exported")
    if consistency.dispute_id != case.dispute_id:
        raise EvidencePacketError("consistency report belongs to a different case")
    if consistency.status != ConsistencyStatus.CONSISTENT:
        raise EvidencePacketError(
            "current evidence is not cross-source consistent; reassess before export"
        )

    by_file_id = {record.metadata.file_id: (record, content) for record, content in files}
    evidence_entries: list[dict[str, object]] = []
    evidence_blobs: list[tuple[str, bytes]] = []
    for citation in draft.citations:
        row = by_file_id.get(citation.source_file_id)
        if row is None:
            raise EvidencePacketError(
                f"cited file {citation.source_file_id} is unavailable"
            )
        record, content = row
        digest = hashlib.sha256(content).hexdigest()
        if record.metadata.dispute_id != case.dispute_id:
            raise EvidencePacketError("cited evidence belongs to a different case")
        if digest != record.metadata.sha256 or digest != citation.source_sha256:
            raise EvidencePacketError(
                f"cited file {citation.source_file_id} failed its SHA-256 check"
            )
        if len(content) != record.metadata.size_bytes:
            raise EvidencePacketError(
                f"cited file {citation.source_file_id} failed its size check"
            )
        if record.metadata.original_name != citation.source_name:
            raise EvidencePacketError(
                f"cited file {citation.source_file_id} has inconsistent provenance"
            )
        packet_path = (
            f"evidence/{citation.label}_{_safe_packet_name(record.metadata.original_name)}"
        )
        evidence_entries.append(
            {
                "citation": citation.label,
                "evidence_id": citation.evidence_id,
                "evidence_type": citation.evidence_type,
                "file_id": record.metadata.file_id,
                "original_name": record.metadata.original_name,
                "packet_path": packet_path,
                "content_type": record.metadata.content_type,
                "size_bytes": record.metadata.size_bytes,
                "sha256": digest,
                "claim": citation.claim,
            }
        )
        evidence_blobs.append((packet_path, content))

    consistency_json = consistency.model_dump(mode="json")
    consistency_sha256 = _json_sha256(consistency_json)
    manifest_core = {
        "format": PACKET_FORMAT,
        "dispute_id": case.dispute_id,
        "draft_id": draft.draft_id,
        "draft_content_sha256": draft.content_sha256,
        "review_id": review.review_id,
        "review_decision": review.decision,
        "reviewed_at": review.created_at,
        "reviewer_label": review.reviewer_label,
        "consistency_status": consistency.status,
        "consistency_report_sha256": consistency_sha256,
        "evidence": evidence_entries,
    }
    manifest_sha256 = _json_sha256(manifest_core)
    manifest = {**manifest_core, "manifest_sha256": manifest_sha256}
    timestamp = review.created_at.astimezone(UTC)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        _write_json(archive, "manifest.json", manifest, timestamp)
        _write_json(
            archive,
            "case.json",
            case.model_copy(update={"evidence": []}).model_dump(mode="json"),
            timestamp,
        )
        _write_json(
            archive,
            "draft.json",
            draft.model_dump(mode="json"),
            timestamp,
        )
        _write_json(
            archive,
            "review.json",
            review.model_dump(mode="json"),
            timestamp,
        )
        _write_json(
            archive,
            "consistency-report.json",
            consistency_json,
            timestamp,
        )
        _write_bytes(
            archive,
            "response.txt",
            f"{draft.subject}\n\n{draft.body}\n".encode(),
            timestamp,
        )
        for path, content in evidence_blobs:
            _write_bytes(archive, path, content, timestamp)

    packet_bytes = output.getvalue()
    return EvidencePacket(
        content=packet_bytes,
        sha256=hashlib.sha256(packet_bytes).hexdigest(),
        manifest_sha256=manifest_sha256,
    )


def _write_json(
    archive: zipfile.ZipFile,
    path: str,
    value: object,
    timestamp: datetime,
) -> None:
    content = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    _write_bytes(archive, path, content, timestamp)


def _write_bytes(
    archive: zipfile.ZipFile,
    path: str,
    content: bytes,
    timestamp: datetime,
) -> None:
    info = zipfile.ZipInfo(path, date_time=timestamp.timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_packet_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", value).lstrip(".")
    return normalized[:255] or "evidence"
