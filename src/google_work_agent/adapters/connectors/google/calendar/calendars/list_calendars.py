"""Canonical Google Calendar list-calendars connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class ListCalendarsOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, page_token: str | None, page_size: int):
        return self._gateway.list_calendars(page_token=page_token, page_size=page_size)
