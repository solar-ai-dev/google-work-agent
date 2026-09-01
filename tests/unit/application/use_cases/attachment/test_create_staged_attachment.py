"""Exact ownership smoke gate for the canonical Application module."""

from pathlib import Path

import pytest

from google_work_agent.adapters.system.filesystem_attachment_staging import (
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentCommand,
    CreateStagedAttachmentHandler,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure


def test_staging_replays_same_explicit_command_without_duplicate_artifact(tmp_path: Path) -> None:
    staging = FilesystemAttachmentStagingAdapter(staging_dir=tmp_path / "staging")
    handler = CreateStagedAttachmentHandler(
        staging=staging,
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
    )
    command = CreateStagedAttachmentCommand(
        command_id="stage-1",
        file_bytes=b"attachment",
        filename="note.txt",
        mime_type="text/plain",
    )

    first = handler(command)
    second = handler(command)

    assert first.replayed is False
    assert second.replayed is True
    assert second.attachment == first.attachment
    assert len(tuple((tmp_path / "staging").glob("*.bin"))) == 1


def test_staging_normalizes_invalid_filename_without_filesystem_leak(tmp_path: Path) -> None:
    handler = CreateStagedAttachmentHandler(
        staging=FilesystemAttachmentStagingAdapter(staging_dir=tmp_path / "staging"),
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
    )

    with pytest.raises(ConnectorOperationFailure) as caught:
        handler(
            CreateStagedAttachmentCommand(
                command_id="stage-invalid",
                file_bytes=b"attachment",
                filename="../secret.txt",
                mime_type="text/plain",
            )
        )

    assert caught.value.detail_code == "ATTACHMENT_FILENAME_INVALID"
