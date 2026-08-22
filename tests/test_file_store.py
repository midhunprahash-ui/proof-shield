import hashlib

import pytest

from proofshield.file_store import (
    MAX_EVIDENCE_FILE_BYTES,
    EvidenceFileError,
    EvidenceFileTooLarge,
    LocalEvidenceFileStore,
    MalformedEvidenceFile,
    UnsupportedEvidenceFile,
    safe_original_name,
)


def test_file_is_stored_by_content_hash(tmp_path) -> None:
    store = LocalEvidenceFileStore(tmp_path / "evidence")
    content = b"%PDF-1.4 synthetic invoice"

    stored = store.save(content, content_type="application/pdf")

    expected_digest = hashlib.sha256(content).hexdigest()
    assert stored.sha256 == expected_digest
    assert stored.storage_key == expected_digest
    assert (tmp_path / "evidence" / expected_digest).read_bytes() == content


def test_same_content_is_reused_without_changing_bytes(tmp_path) -> None:
    store = LocalEvidenceFileStore(tmp_path / "evidence")
    first = store.save(b"same", content_type="text/plain")
    second = store.save(b"same", content_type="text/plain; charset=utf-8")

    assert first == second
    assert len(list((tmp_path / "evidence").iterdir())) == 1


@pytest.mark.parametrize(
    ("content", "content_type", "error"),
    [
        (b"", "text/plain", EvidenceFileError),
        (b"data", "application/octet-stream", UnsupportedEvidenceFile),
        (b"x" * (MAX_EVIDENCE_FILE_BYTES + 1), "text/plain", EvidenceFileTooLarge),
    ],
)
def test_invalid_files_are_rejected(content, content_type, error, tmp_path) -> None:
    store = LocalEvidenceFileStore(tmp_path / "evidence")

    with pytest.raises(error):
        store.save(content, content_type=content_type)


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
    content: bytes, content_type: str, tmp_path
) -> None:
    store = LocalEvidenceFileStore(tmp_path / "evidence")

    with pytest.raises(MalformedEvidenceFile):
        store.save(content, content_type=content_type)
