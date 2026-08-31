"""Owner-local projections over exact persisted execution-attempt facts."""

from json import JSONDecodeError, loads

from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.ports.persistence.audit_event_repository import (
    AuditEventCursor,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def latest_attempt_for_action(
    unit_of_work: UnitOfWork,
    action_id: str,
) -> ExecutionAttemptRecord | None:
    """Resolve the latest Attempt via action audit identity and exact repository get."""

    events = unit_of_work.audits.list_page(AuditEventCursor(action_id=action_id), 500)
    attempt_ids = tuple(
        attempt_id
        for event in events
        if (attempt_id := _attempt_id(event.metadata_json)) is not None
    )
    attempts = tuple(
        attempt
        for attempt_id in dict.fromkeys(attempt_ids)
        if (attempt := unit_of_work.execution_attempts.get(attempt_id)) is not None
    )
    return max(attempts, key=lambda item: (item.attempt_no, item.started_at_ms), default=None)


def _attempt_id(metadata_json: str) -> str | None:
    try:
        metadata = loads(metadata_json)
    except (JSONDecodeError, TypeError):
        return None
    if not isinstance(metadata, dict):
        return None
    attributes = metadata.get("attributes", metadata)
    if not isinstance(attributes, dict):
        return None
    attempt_id = attributes.get("attempt_id")
    return attempt_id if isinstance(attempt_id, str) else None


__all__ = ["latest_attempt_for_action"]
