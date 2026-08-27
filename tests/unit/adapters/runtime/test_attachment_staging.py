from __future__ import annotations

from dataclasses import replace

import pytest

from google_work_agent.adapters.system.filesystem_attachment_staging import (
    AttachmentStagingError,
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.ports.system.attachment_staging_port import (
    StagedAttachmentDescriptorV1,
)


def test_stage_replay_and_verified_read_are_deterministic(tmp_path) -> None:
    staging = FilesystemAttachmentStagingAdapter(staging_dir=tmp_path, now_ms=lambda: 1_000)

    first = staging.stage("operation-1", b"file bytes", "report.pdf", "application/pdf")
    replay = staging.stage("operation-1", b"file bytes", "report.pdf", "application/pdf")

    assert replay == first
    assert staging.open_bytes(first.staged_attachment_id) == b"file bytes"
    assert staging.reconcile_stage("operation-1").status == "COMPLETED"


def test_stage_replay_rejects_different_payload(tmp_path) -> None:
    staging = FilesystemAttachmentStagingAdapter(staging_dir=tmp_path, now_ms=lambda: 1_000)
    staging.stage("operation-1", b"first", "a.txt", "text/plain")

    with pytest.raises(AttachmentStagingError, match="ATTACHMENT_OPERATION_CONFLICT"):
        staging.stage("operation-1", b"second", "a.txt", "text/plain")


def test_verified_read_rejects_tampered_descriptor_and_expiry(tmp_path) -> None:
    clock = {"now": 1_000}
    staging = FilesystemAttachmentStagingAdapter(
        staging_dir=tmp_path,
        now_ms=lambda: clock["now"],
    )
    descriptor = staging.stage("operation-1", b"bytes", "a.txt", "text/plain")

    with pytest.raises(AttachmentStagingError, match="ATTACHMENT_HASH_MISMATCH"):
        staging.read_verified(replace(descriptor, sha256="f" * 64))

    clock["now"] = descriptor.expires_at_ms
    with pytest.raises(AttachmentStagingError, match="ATTACHMENT_STAGING_EXPIRED"):
        staging.open_bytes(descriptor.staged_attachment_id)


def test_descriptor_json_round_trip_and_malformed_rejection() -> None:
    descriptor = StagedAttachmentDescriptorV1(1, "id-1", "a.txt", "text/plain", 5, "a" * 64, 9)

    assert StagedAttachmentDescriptorV1.from_json(descriptor.to_json()) == descriptor
    with pytest.raises(AttachmentStagingError, match="ATTACHMENT_DESCRIPTOR_MALFORMED"):
        StagedAttachmentDescriptorV1.from_json({"filename": "a.txt"})
