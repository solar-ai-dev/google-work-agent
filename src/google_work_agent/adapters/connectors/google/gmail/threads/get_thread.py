"""Canonical Gmail thread detail connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class GetThreadOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, thread_id: str):
        return self._gateway.get_gmail_thread(thread_id=thread_id)
