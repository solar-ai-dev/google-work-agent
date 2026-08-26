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
import secrets
import time
from collections.abc import Callable
from pathlib import Path

from google_work_agent.ports.system.attachment_staging_port import (
    AttachmentDescriptor,
    AttachmentStagingError,
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

    def stage(self, *, data: bytes, filename: str, mime_type: str) -> AttachmentDescriptor:
        if not data:
            raise AttachmentStagingError("ATTACHMENT_EMPTY")
        if len(data) > MAX_STAGED_FILE_BYTES:
            raise AttachmentStagingError("ATTACHMENT_TOO_LARGE")
        if not filename or len(filename) > 255 or "/" in filename or "\\" in filename:
            raise AttachmentStagingError("ATTACHMENT_FILENAME_INVALID")
        staged_attachment_id = secrets.token_urlsafe(_ID_ALPHABET_BYTES)
        digest = hashlib.sha256(data).hexdigest()
        expires_at_ms = self._now_ms() + STAGING_TTL_MS
        self._data_path(staged_attachment_id).write_bytes(data)
        self._meta_path(staged_attachment_id).write_text(
            json.dumps(
                {
                    "filename": filename,
                    "mime_type": mime_type,
                    "size_bytes": len(data),
                    "sha256": digest,
                    "expires_at_ms": expires_at_ms,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return AttachmentDescriptor(
            staged_attachment_id=staged_attachment_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=digest,
        )

    def read_verified(self, descriptor: AttachmentDescriptor) -> bytes:
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

    def verify_descriptor(self, descriptor: AttachmentDescriptor) -> None:
        self.read_verified(descriptor)

    def _remove(self, staged_attachment_id: str) -> None:
        for path in (self._data_path(staged_attachment_id), self._meta_path(staged_attachment_id)):
            path.unlink(missing_ok=True)

    def _data_path(self, staged_attachment_id: str) -> Path:
        return self._staging_dir / f"{staged_attachment_id}.bin"

    def _meta_path(self, staged_attachment_id: str) -> Path:
        return self._staging_dir / f"{staged_attachment_id}.meta.json"
