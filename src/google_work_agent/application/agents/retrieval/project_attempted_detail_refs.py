"""Project completed detail-read identities from durable Retrieval attempts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)

_DETAIL_IDENTITY_BY_TOOL = {
    "gmail_get_thread": ("thread_id", "gmail_thread:"),
    "gmail_get_message": ("message_id", "gmail_message:"),
    "gmail_get_draft": ("draft_id", "gmail_draft:"),
    "gmail_get_attachment": ("attachment_id", "gmail_attachment:"),
    "tasks_get_task": ("task_id", "task:"),
    "calendar_get_event": ("event_id", "calendar_event:"),
}


def project_attempted_detail_refs(attempts: Iterable[QueryAttemptV1]) -> list[str]:
    """Return stable candidate refs for every completed detail read in attempt history."""

    refs: list[str] = []
    for attempt in attempts:
        if attempt["operation_kind"] != "DETAIL_FETCH" or attempt["stop_reason"] is None:
            continue
        query_spec = attempt["query_spec"]
        identity = _DETAIL_IDENTITY_BY_TOOL.get(query_spec["tool_id"])
        arguments = query_spec["canonical_arguments"]
        if identity is None or not isinstance(arguments, Mapping):
            continue
        argument_name, prefix = identity
        resource_id = arguments.get(argument_name)
        if isinstance(resource_id, str) and resource_id:
            refs.append(f"{prefix}{resource_id}")
    return list(dict.fromkeys(refs))


__all__ = ["project_attempted_detail_refs"]
