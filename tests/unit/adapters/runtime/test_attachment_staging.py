"""Unit tests for the local Gmail attachment staging service (WP4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from google_work_agent.adapters.runtime.attachment_staging import (
    AttachmentDescriptor,
    AttachmentStagingError,
    LocalAttachmentStaging,
)


def _staging(tmp_path: Path, *, now_ms: int = 1_000_000) -> LocalAttachmentStaging:
    return LocalAttachmentStaging(staging_dir=tmp_path / "attachments", now_ms=lambda: now_ms)


def test_stage_then_read_verified_round_trips_bytes(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    descriptor = staging.stage(
        data=b"file bytes", filename="report.pdf", mime_type="application/pdf"
    )

    assert descriptor.filename == "report.pdf"
    assert descriptor.mime_type == "application/pdf"
    assert descriptor.size_bytes == len(b"file bytes")
    assert len(descriptor.sha256) == 64

    assert staging.read_verified(descriptor) == b"file bytes"


def test_stage_rejects_empty_bytes(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.stage(data=b"", filename="empty.txt", mime_type="text/plain")
    assert exc_info.value.safe_code == "ATTACHMENT_EMPTY"


def test_stage_rejects_oversized_bytes(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    from google_work_agent.adapters.runtime.attachment_staging import MAX_STAGED_FILE_BYTES

    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.stage(
            data=b"x" * (MAX_STAGED_FILE_BYTES + 1),
            filename="big.bin",
            mime_type="application/octet-stream",
        )
    assert exc_info.value.safe_code == "ATTACHMENT_TOO_LARGE"


def test_stage_rejects_path_like_filenames(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.stage(data=b"data", filename="../../etc/passwd", mime_type="text/plain")
    assert exc_info.value.safe_code == "ATTACHMENT_FILENAME_INVALID"


def test_read_verified_rejects_unknown_staging_id(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    fake = AttachmentDescriptor(
        staged_attachment_id="does-not-exist",
        filename="a.txt",
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
    )
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(fake)
    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_MISSING"


def test_read_verified_rejects_expired_staging(tmp_path: Path) -> None:
    clock = {"now": 1_000_000}
    staging = LocalAttachmentStaging(
        staging_dir=tmp_path / "attachments", now_ms=lambda: clock["now"]
    )
    descriptor = staging.stage(data=b"bytes", filename="a.txt", mime_type="text/plain")
    clock["now"] += 20 * 60 * 1000  # advance past the 15 minute TTL

    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(descriptor)
    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_EXPIRED"


def test_read_verified_rejects_size_mismatch(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    descriptor = staging.stage(data=b"bytes", filename="a.txt", mime_type="text/plain")
    tampered = AttachmentDescriptor(
        staged_attachment_id=descriptor.staged_attachment_id,
        filename=descriptor.filename,
        mime_type=descriptor.mime_type,
        size_bytes=descriptor.size_bytes + 1,
        sha256=descriptor.sha256,
    )
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(tampered)
    assert exc_info.value.safe_code == "ATTACHMENT_SIZE_MISMATCH"


def test_read_verified_rejects_hash_mismatch(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    descriptor = staging.stage(data=b"bytes", filename="a.txt", mime_type="text/plain")
    tampered = AttachmentDescriptor(
        staged_attachment_id=descriptor.staged_attachment_id,
        filename=descriptor.filename,
        mime_type=descriptor.mime_type,
        size_bytes=descriptor.size_bytes,
        sha256="f" * 64,
    )
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(tampered)
    assert exc_info.value.safe_code == "ATTACHMENT_HASH_MISMATCH"


def test_read_verified_rejects_descriptor_mismatch_on_filename(tmp_path: Path) -> None:
    staging = _staging(tmp_path)
    descriptor = staging.stage(data=b"bytes", filename="a.txt", mime_type="text/plain")
    tampered = AttachmentDescriptor(
        staged_attachment_id=descriptor.staged_attachment_id,
        filename="different.txt",
        mime_type=descriptor.mime_type,
        size_bytes=descriptor.size_bytes,
        sha256=descriptor.sha256,
    )
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(tampered)
    assert exc_info.value.safe_code == "ATTACHMENT_DESCRIPTOR_MISMATCH"


def test_cleanup_expired_removes_only_expired_entries(tmp_path: Path) -> None:
    clock = {"now": 1_000_000}
    staging = LocalAttachmentStaging(
        staging_dir=tmp_path / "attachments", now_ms=lambda: clock["now"]
    )
    stale = staging.stage(data=b"stale", filename="stale.txt", mime_type="text/plain")
    clock["now"] += 20 * 60 * 1000
    fresh = staging.stage(data=b"fresh", filename="fresh.txt", mime_type="text/plain")

    staging.cleanup_expired()

    assert staging.read_verified(fresh) == b"fresh"
    with pytest.raises(AttachmentStagingError) as exc_info:
        staging.read_verified(stale)
    assert exc_info.value.safe_code == "ATTACHMENT_STAGING_MISSING"


def test_descriptor_json_round_trip() -> None:
    descriptor = AttachmentDescriptor(
        staged_attachment_id="id-1",
        filename="a.txt",
        mime_type="text/plain",
        size_bytes=5,
        sha256="a" * 64,
    )
    restored = AttachmentDescriptor.from_json(descriptor.to_json())
    assert restored == descriptor


def test_descriptor_from_json_rejects_malformed_payload() -> None:
    with pytest.raises(AttachmentStagingError) as exc_info:
        AttachmentDescriptor.from_json({"filename": "a.txt"})
    assert exc_info.value.safe_code == "ATTACHMENT_DESCRIPTOR_MALFORMED"
