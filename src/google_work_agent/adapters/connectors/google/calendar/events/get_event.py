"""Canonical Google Calendar event detail/verification connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class GetEventOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, calendar_id: str, event_id: str):
        return self._gateway.get_calendar_event(
            calendar_id=calendar_id, event_id=event_id
        )
