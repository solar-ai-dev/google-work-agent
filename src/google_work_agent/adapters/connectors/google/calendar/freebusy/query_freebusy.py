"""Canonical Google Calendar free/busy connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway, TimeRange


class QueryFreeBusyOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, calendar_ids: tuple[str, ...], time_range: TimeRange):
        return self._gateway.query_freebusy(
            calendar_ids=calendar_ids, time_range=time_range
        )
