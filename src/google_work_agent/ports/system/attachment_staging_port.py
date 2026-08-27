"""Gmail attachment READ and outbound staging port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, cast

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


class AttachmentStagingError(RuntimeError):
    """A sanitized staging failure whose code never contains file content."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class StagedAttachmentDescriptorV1:
    """Minimal descriptor carried in outbound business arguments and claims."""

    schema_version: Literal[1]
    staged_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    expires_at_ms: int

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "staged_attachment_id": self.staged_attachment_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "expires_at_ms": self.expires_at_ms,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> StagedAttachmentDescriptorV1:
        try:
            return cls(
                schema_version=1,
                staged_attachment_id=str(payload["staged_attachment_id"]),
                filename=str(payload["filename"]),
                mime_type=str(payload["mime_type"]),
                size_bytes=int(cast(int, payload["size_bytes"])),
                sha256=str(payload["sha256"]),
                expires_at_ms=int(cast(int, payload["expires_at_ms"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AttachmentStagingError("ATTACHMENT_DESCRIPTOR_MALFORMED") from error


class AttachmentStagingPort(Protocol):
    """Stage outbound attachment bytes behind a local storage boundary."""

    def stage(
        self,
        operation_ref: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> StagedAttachmentDescriptorV1: ...

    def reconcile_stage(self, operation_ref: str) -> OperationalReconcileResultV1: ...

    def open_bytes(self, staged_attachment_id: str) -> bytes: ...

    def delete(self, staged_attachment_id: str) -> None: ...
