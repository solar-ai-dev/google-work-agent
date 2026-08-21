"""Canonical Google Calendar event update connector operation."""

from __future__ import annotations

from typing import Any

from google_work_agent.ports import GoogleWorkspaceGateway


class UpdateEventOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, object] | None,
    ):
        return self._gateway.update_calendar_event(
            calendar_id=calendar_id,
            event_id=event_id,
            payload=payload,
            claim_context=claim_context,
        )
