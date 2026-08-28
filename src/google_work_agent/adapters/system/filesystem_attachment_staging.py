"""Local filesystem staging for outbound Gmail attachment bytes.

Only this module ever holds raw attachment bytes. Every caller outside of
this module (API routes, Application services, the MCP write handlers)
exchanges an ``AttachmentDescriptor`` -- filename/mime_type/size_bytes/sha256
plus a random staging identity -- never the bytes themselves. This keeps
attachment content out of the domain database, LLM input, agent state, and
trace/audit output by construction rather than by convention.

The MCP child process and the local API service are separate processes on
the same machine; they share this staging directory by path (see
``GWA_ATTACHMENT_STAGING_DIR``) rather than through any RPC channel, so
attachment bytes never cross the size-limited MCP stdio transport.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from google_work_agent.ports.system.attachment_staging_port import (
    AttachmentStagingError,
    StagedAttachmentDescriptorV1,
)
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)

STAGING_TTL_MS = 15 * 60 * 1000
MAX_STAGED_FILE_BYTES = 8 * 1024 * 1024
_ID_ALPHABET_BYTES = 24
ATTACHMENT_STAGING_DIR_ENV = "GWA_ATTACHMENT_STAGING_DIR"


def _default_now_ms() -> int:
    return int(time.time() * 1000)


class FilesystemAttachmentStagingAdapter:
    """User-scoped, TTL'd, filesystem-backed attachment byte staging area."""

    def __init__(
        self,
        *,
        staging_dir: Path,
        now_ms: Callable[[], int] = _default_now_ms,
    ) -> None:
        self._staging_dir = staging_dir
        self._staging_dir.mkdir(parents=True, exist_ok=True)
        self._now_ms = now_ms

    def cleanup_expired(self) -> None:
        """Remove every staged file/metadata pair past its TTL.

        Safe to call at any time, including at process startup: it only
        ever removes files whose recorded ``expires_at_ms`` has passed.
        """

        if not self._staging_dir.is_dir():
            return
        now_ms = self._now_ms()
        for meta_path in self._staging_dir.glob("*.meta.json"):
            staged_attachment_id = meta_path.name.removesuffix(".meta.json")
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                expired = int(meta["expires_at_ms"]) <= now_ms
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                expired = True
            if expired:
                self._remove(staged_attachment_id)

    def stage(
        self,
        operation_ref: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
    ) -> StagedAttachmentDescriptorV1:
        if not operation_ref:
            raise AttachmentStagingError("OPERATION_REF_REQUIRED")
        if not file_bytes:
            raise AttachmentStagingError("ATTACHMENT_EMPTY")
        if len(file_bytes) > MAX_STAGED_FILE_BYTES:
            raise AttachmentStagingError("ATTACHMENT_TOO_LARGE")
        if not filename or len(filename) > 255 or "/" in filename or "\\" in filename:
            raise AttachmentStagingError("ATTACHMENT_FILENAME_INVALID")
        if (
            not mime_type
            or len(mime_type) > 255
            or "\r" in mime_type
            or "\n" in mime_type
            or "/" not in mime_type
        ):
            raise AttachmentStagingError("ATTACHMENT_MIME_TYPE_INVALID")
        staged_attachment_id = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        digest = hashlib.sha256(file_bytes).hexdigest()
        expires_at_ms = self._now_ms() + STAGING_TTL_MS
        existing_meta = self._metadata_for_operation(operation_ref)
        if existing_meta is not None:
            if (
                str(existing_meta.get("filename")) != filename
                or str(existing_meta.get("mime_type")) != mime_type
                or int(cast(int | str, existing_meta.get("size_bytes", -1))) != len(file_bytes)
                or str(existing_meta.get("sha256")) != digest
            ):
                raise AttachmentStagingError("ATTACHMENT_OPERATION_CONFLICT")
            return self._descriptor_from_metadata(staged_attachment_id, existing_meta)
        metadata = {
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
            "sha256": digest,
            "expires_at_ms": expires_at_ms,
            "operation_ref": operation_ref,
        }
        self._atomic_write(self._data_path(staged_attachment_id), file_bytes)
        try:
            self._atomic_write(
                self._meta_path(staged_attachment_id),
                json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
        except Exception:
            self._data_path(staged_attachment_id).unlink(missing_ok=True)
            raise
        return StagedAttachmentDescriptorV1(
            schema_version=1,
            staged_attachment_id=staged_attachment_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            sha256=digest,
            expires_at_ms=expires_at_ms,
        )

    def open_bytes(self, staged_attachment_id: str) -> bytes:
        descriptor = self._load_descriptor(staged_attachment_id)
        return self.read_verified(descriptor)

    def read_verified(self, descriptor: StagedAttachmentDescriptorV1) -> bytes:
        """Re-read staged bytes and verify them against ``descriptor``.

        Raises on anything that would let stale, tampered, or mismatched
        content reach a Google write: missing staging id, expired TTL, size
        mismatch, hash mismatch, or a descriptor that no longer matches what
        was actually staged.
        """

        meta_path = self._meta_path(descriptor.staged_attachment_id)
        data_path = self._data_path(descriptor.staged_attachment_id)
        if not meta_path.is_file() or not data_path.is_file():
            raise AttachmentStagingError("ATTACHMENT_STAGING_MISSING")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AttachmentStagingError("ATTACHMENT_STAGING_MISSING") from error
        if int(meta["expires_at_ms"]) <= self._now_ms():
            self._remove(descriptor.staged_attachment_id)
            raise AttachmentStagingError("ATTACHMENT_STAGING_EXPIRED")
        if (
            str(meta["filename"]) != descriptor.filename
            or str(meta["mime_type"]) != descriptor.mime_type
        ):
            raise AttachmentStagingError("ATTACHMENT_DESCRIPTOR_MISMATCH")
        if int(meta["size_bytes"]) != descriptor.size_bytes:
            raise AttachmentStagingError("ATTACHMENT_SIZE_MISMATCH")
        if str(meta["sha256"]) != descriptor.sha256:
            raise AttachmentStagingError("ATTACHMENT_HASH_MISMATCH")
        data = data_path.read_bytes()
        if len(data) != descriptor.size_bytes:
            raise AttachmentStagingError("ATTACHMENT_SIZE_MISMATCH")
        if hashlib.sha256(data).hexdigest() != descriptor.sha256:
            raise AttachmentStagingError("ATTACHMENT_HASH_MISMATCH")
        return data

    def verify_descriptor(self, descriptor: StagedAttachmentDescriptorV1) -> None:
        self.read_verified(descriptor)

    def reconcile_stage(self, operation_ref: str) -> OperationalReconcileResultV1:
        descriptor = self._descriptor_for_operation(operation_ref)
        if descriptor is None:
            return OperationalReconcileResultV1("SAFE_TO_RETRY", None, None)
        return OperationalReconcileResultV1(
            "COMPLETED",
            descriptor.staged_attachment_id,
            {"staged_attachment_id": descriptor.staged_attachment_id},
        )

    def delete(self, staged_attachment_id: str) -> None:
        self._remove(staged_attachment_id)

    def _descriptor_for_operation(self, operation_ref: str) -> StagedAttachmentDescriptorV1 | None:
        staged_attachment_id = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        metadata = self._metadata_for_operation(operation_ref)
        return (
            None
            if metadata is None
            else self._descriptor_from_metadata(staged_attachment_id, metadata)
        )

    def _metadata_for_operation(self, operation_ref: str) -> dict[str, object] | None:
        staged_attachment_id = hashlib.sha256(operation_ref.encode("utf-8")).hexdigest()[:32]
        meta_path = self._meta_path(staged_attachment_id)
        if not meta_path.is_file():
            return None
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict) or metadata.get("operation_ref") != operation_ref:
            return None
        return metadata

    def _load_descriptor(self, staged_attachment_id: str) -> StagedAttachmentDescriptorV1:
        meta_path = self._meta_path(staged_attachment_id)
        if not meta_path.is_file():
            raise AttachmentStagingError("ATTACHMENT_STAGING_MISSING")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                raise TypeError("metadata must be an object")
            return self._descriptor_from_metadata(staged_attachment_id, meta)
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AttachmentStagingError("ATTACHMENT_STAGING_MISSING") from error

    def _remove(self, staged_attachment_id: str) -> None:
        for path in (self._data_path(staged_attachment_id), self._meta_path(staged_attachment_id)):
            path.unlink(missing_ok=True)

    def _data_path(self, staged_attachment_id: str) -> Path:
        return self._staging_dir / f"{staged_attachment_id}.bin"

    def _meta_path(self, staged_attachment_id: str) -> Path:
        return self._staging_dir / f"{staged_attachment_id}.meta.json"

    @staticmethod
    def _descriptor_from_metadata(
        staged_attachment_id: str, metadata: dict[str, object]
    ) -> StagedAttachmentDescriptorV1:
        try:
            return StagedAttachmentDescriptorV1(
                schema_version=1,
                staged_attachment_id=staged_attachment_id,
                filename=str(metadata["filename"]),
                mime_type=str(metadata["mime_type"]),
                size_bytes=int(cast(int | str, metadata["size_bytes"])),
                sha256=str(metadata["sha256"]),
                expires_at_ms=int(cast(int | str, metadata["expires_at_ms"])),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AttachmentStagingError("ATTACHMENT_STAGING_MISSING") from error

    def _atomic_write(self, path: Path, content: bytes) -> None:
        temp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        try:
            with temp_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(path)
            try:
                directory_fd = os.open(self._staging_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Windows does not expose directory fsync through Python.
                pass
        finally:
            temp_path.unlink(missing_ok=True)
