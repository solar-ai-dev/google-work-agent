"""Canonical Gmail draft detail/verification connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class GetDraftOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, draft_id: str):
        return self._gateway.get_gmail_draft(draft_id=draft_id)
