"""Stage an outbound attachment through crash-safe operational replay."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.attachment_staging_port import (
    AttachmentStagingPort,
    StagedAttachmentDescriptorV1,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class CreateStagedAttachmentCommand:
    command_id: str
    file_bytes: bytes
    filename: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class CreateStagedAttachmentResult:
    attachment: StagedAttachmentDescriptorV1
    operation_ref: str
    replayed: bool


class CreateStagedAttachmentHandler:
    def __init__(
        self, *, staging: AttachmentStagingPort, replay: OperationalCommandReplayPort
    ) -> None:
        self._staging = staging
        self._replay = replay

    def __call__(self, command: CreateStagedAttachmentCommand) -> CreateStagedAttachmentResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._staging.stage(
                ref, command.file_bytes, command.filename, command.mime_type
            )
            return value.staged_attachment_id, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="CREATE_STAGED_ATTACHMENT",
            request_payload={
                "filename": command.filename,
                "mime_type": command.mime_type,
                "size_bytes": len(command.file_bytes),
                "sha256": sha256(command.file_bytes).hexdigest(),
            },
            reconcile=self._staging.reconcile_stage,
            execute=execute,
        )
        return CreateStagedAttachmentResult(
            attachment=StagedAttachmentDescriptorV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = [
    "CreateStagedAttachmentCommand",
    "CreateStagedAttachmentHandler",
    "CreateStagedAttachmentResult",
]
