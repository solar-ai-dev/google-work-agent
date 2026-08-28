"""Connector-owner-local Google Workspace value and error contracts.

The provider operation boundary is owned by the exact connector ports under
``ports.connector``.  This module intentionally contains no gateway Protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

type JsonValue = Any


class ResourceType(StrEnum):
    GMAIL_THREAD = "gmail_thread"
    GMAIL_MESSAGE = "gmail_message"
    GMAIL_DRAFT = "gmail_draft"
    TASK_LIST = "task_list"
    TASK = "task"
    CALENDAR = "calendar"
    CALENDAR_EVENT = "calendar_event"
    CALENDAR_FREEBUSY = "calendar_freebusy"


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    fixture_snapshot_id: str
    resource_type: ResourceType
    resource_id: str
    parent_id: str | None
    related_resource_ids: tuple[str, ...]
    version: str
    recovery_fingerprint: str | None
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ResourcePage:
    items: tuple[ResourceSnapshot, ...]
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class GmailAttachmentMetadata:
    message_id: str
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class GmailThreadDetail:
    thread_id: str
    message_id: str
    rfc822_message_id: str | None
    sender_name: str | None
    sender_email: str | None
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str | None
    received_at: str | None
    body: str | None
    attachments: tuple[GmailAttachmentMetadata, ...]
    version: str


@dataclass(frozen=True, slots=True)
class FreeBusyInterval:
    start: str
    end: str
    transparency: str


@dataclass(frozen=True, slots=True)
class FreeBusyCalendar:
    calendar_id: str
    intervals: tuple[FreeBusyInterval, ...]


@dataclass(frozen=True, slots=True)
class TimeRange:
    start: str
    end: str

    def __post_init__(self) -> None:
        start = _parse_rfc3339(self.start)
        end = _parse_rfc3339(self.end)
        if start >= end:
            raise ValueError("time range start must precede end")


class GoogleWorkspaceErrorCode(StrEnum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    TIMEOUT = "TIMEOUT"
    CONNECTION_CLOSED = "CONNECTION_CLOSED"
    RESPONSE_MALFORMED = "RESPONSE_MALFORMED"
    VERIFICATION_MISMATCH = "VERIFICATION_MISMATCH"
    RESOURCE_VERSION_CHANGED = "RESOURCE_VERSION_CHANGED"
    DUPLICATE_RECOVERY_CANDIDATE = "DUPLICATE_RECOVERY_CANDIDATE"
    NO_RECOVERY_CANDIDATE = "NO_RECOVERY_CANDIDATE"


class DeliveryCertainty(StrEnum):
    NOT_SENT = "NOT_SENT"
    MAY_HAVE_BEEN_SENT = "MAY_HAVE_BEEN_SENT"
    SENT_RESPONSE_LOST = "SENT_RESPONSE_LOST"


class GoogleWorkspaceGatewayError(RuntimeError):
    """Compatibility error value; it is not an integration authority."""

    def __init__(
        self,
        *,
        code: GoogleWorkspaceErrorCode,
        message: str,
        delivered: bool,
        mutated: bool,
        mcp_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.delivered = delivered
        self.mutated = mutated
        self.mcp_request_id = mcp_request_id
        self.delivery_certainty = (
            DeliveryCertainty.NOT_SENT
            if not delivered
            else DeliveryCertainty.SENT_RESPONSE_LOST
            if mutated
            else DeliveryCertainty.MAY_HAVE_BEEN_SENT
        )


def _parse_rfc3339(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("time range value is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("time range must use RFC3339") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("time range must include a timezone")
    return parsed
