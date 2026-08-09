"""Google Workspace gateway port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

type JsonValue = Any


class ResourceType(StrEnum):
    """Supported fixture-backed Google Workspace resource types."""

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
    """Immutable projection for one Google Workspace resource snapshot."""

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
    """Deterministic paginated Google Workspace result."""

    items: tuple[ResourceSnapshot, ...]
    next_page_token: str | None


@dataclass(frozen=True, slots=True)
class FreeBusyInterval:
    """One busy interval returned by the gateway."""

    start: str
    end: str
    transparency: str


@dataclass(frozen=True, slots=True)
class FreeBusyCalendar:
    """Free/busy response for one calendar."""

    calendar_id: str
    intervals: tuple[FreeBusyInterval, ...]


class GoogleWorkspaceErrorCode(StrEnum):
    """Deterministic fault codes exposed by the fake gateway."""

    AUTH_EXPIRED = "AUTH_EXPIRED"
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
    """Transport knowledge used to select FAILED versus UNKNOWN_RESULT."""

    NOT_SENT = "NOT_SENT"
    MAY_HAVE_BEEN_SENT = "MAY_HAVE_BEEN_SENT"
    SENT_RESPONSE_LOST = "SENT_RESPONSE_LOST"


class GoogleWorkspaceGatewayError(RuntimeError):
    """Gateway error that preserves delivery and mutation semantics."""

    def __init__(
        self,
        *,
        code: GoogleWorkspaceErrorCode,
        message: str,
        delivered: bool,
        mutated: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.delivered = delivered
        self.mutated = mutated
        self.delivery_certainty = (
            DeliveryCertainty.NOT_SENT
            if not delivered
            else DeliveryCertainty.SENT_RESPONSE_LOST
            if mutated
            else DeliveryCertainty.MAY_HAVE_BEEN_SENT
        )


class GoogleWorkspaceGateway(Protocol):
    """Read/write gateway over Google Workspace resources."""

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        """Search Gmail threads."""

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        """Return one Gmail thread snapshot."""

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        """Return one Gmail message snapshot."""

    def create_gmail_draft(
        self,
        *,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Create one Gmail draft."""

    def update_gmail_draft(
        self,
        *,
        draft_id: str,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Update one Gmail draft."""

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        """Return one Gmail draft snapshot."""

    def send_gmail(
        self,
        *,
        draft_id: str,
        recovery_fingerprint: str | None,
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Send one approved Gmail draft and return the provider message identity."""

    def list_task_lists(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        """List task lists."""

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        """List tasks for one task list."""

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        """Return one task snapshot."""

    def create_task(
        self,
        *,
        task_list_id: str,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Create one task."""

    def update_task(
        self,
        *,
        task_list_id: str,
        task_id: str,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Update one task."""

    def list_calendars(
        self,
        *,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        """List calendars."""

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        """List calendar events for one calendar."""

    def query_freebusy(self, *, calendar_ids: tuple[str, ...]) -> tuple[FreeBusyCalendar, ...]:
        """Return free/busy intervals for calendars."""

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        """Return one calendar event snapshot."""

    def create_calendar_event(
        self,
        *,
        calendar_id: str,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Create one calendar event."""

    def update_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        payload: dict[str, JsonValue],
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Update one calendar event."""

    def delete_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        claim_context: dict[str, JsonValue] | None = None,
    ) -> ResourceSnapshot:
        """Delete one approved non-recurring Calendar event."""

    def search_by_recovery_fingerprint(
        self,
        *,
        resource_type: ResourceType,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        """Return recovery candidates for one fingerprint."""
