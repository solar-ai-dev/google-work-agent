"""Canonical Google Tasks delete connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class DeleteTaskOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self, *, task_list_id: str, task_id: str, claim_context: dict[str, object] | None
    ):
        return self._gateway.delete_task(
            task_list_id=task_list_id, task_id=task_id, claim_context=claim_context
        )
