"""Canonical Gmail message detail/verification connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class GetMessageOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, message_id: str):
        return self._gateway.get_gmail_message(message_id=message_id)
