import hashlib

import pytest

from proofshield.file_store import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileError,
    EvidenceFileTooLarge,
    MalformedEvidenceFile,
    UnsupportedEvidenceFile,
    safe_original_name,
)
from proofshield.memory import InMemoryEvidenceFileStore


def test_file_is_stored_by_content_hash() -> None:
    store = InMemoryEvidenceFileStore()
    content = b"%PDF-1.4 synthetic invoice"

    stored = store.save(
        content,
        content_type="application/pdf",
        dispute_id="disp_1",
        file_id="file_1",
    )

    expected_digest = hashlib.sha256(content).hexdigest()
    case_key = hashlib.sha256(b"disp_1").hexdigest()
    assert stored.sha256 == expected_digest
    assert stored.storage_key == f"cases/{case_key}/file_1/{expected_digest}"
    assert store.blobs[stored.storage_key] == content


def test_storage_keys_isolate_files_even_when_content_matches() -> None:
    store = InMemoryEvidenceFileStore()
    first = store.save(
        b"same", content_type="text/plain", dispute_id="disp_1", file_id="file_1"
    )
    second = store.save(
        b"same",
        content_type="text/plain; charset=utf-8",
        dispute_id="disp_1",
        file_id="file_2",
    )

    assert first.sha256 == second.sha256
    assert first.storage_key != second.storage_key
    assert len(store.blobs) == 2


@pytest.mark.parametrize(
    ("content", "content_type", "error"),
    [
        (b"", "text/plain", EvidenceFileError),
        (b"data", "application/octet-stream", UnsupportedEvidenceFile),
        (b"x" * (MAX_EVIDENCE_FILE_BYTES + 1), "text/plain", EvidenceFileTooLarge),
    ],
)
def test_invalid_files_are_rejected(content, content_type, error) -> None:
    store = InMemoryEvidenceFileStore()

    with pytest.raises(error):
        store.save(
            content,
            content_type=content_type,
            dispute_id="disp_1",
            file_id="file_1",
        )


def test_original_filename_is_reduced_to_a_safe_label() -> None:
    assert safe_original_name("../../private/customer.pdf") == "customer.pdf"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"not a pdf", "application/pdf"),
        (b"not png", "image/png"),
        (b"not jpeg", "image/jpeg"),
        (b"{broken", "application/json"),
        (b"\xff", "text/plain"),
    ],
)
def test_declared_content_type_must_match_file_bytes(
    content: bytes, content_type: str
) -> None:
    store = InMemoryEvidenceFileStore()

    with pytest.raises(MalformedEvidenceFile):
        store.save(
            content,
            content_type=content_type,
            dispute_id="disp_1",
            file_id="file_1",
        )
