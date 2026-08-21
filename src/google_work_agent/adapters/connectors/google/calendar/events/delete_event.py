"""Canonical Google Calendar event delete connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class DeleteEventOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self, *, calendar_id: str, event_id: str, claim_context: dict[str, object] | None
    ):
        return self._gateway.delete_calendar_event(
            calendar_id=calendar_id, event_id=event_id, claim_context=claim_context
        )
