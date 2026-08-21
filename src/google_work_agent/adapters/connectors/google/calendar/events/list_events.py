"""Canonical Google Calendar event-list connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class ListEventsOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, calendar_id: str, page_token: str | None, page_size: int):
        return self._gateway.list_calendar_events(
            calendar_id=calendar_id, page_token=page_token, page_size=page_size
        )
