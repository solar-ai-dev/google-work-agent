"""Canonical Google Tasks detail/verification connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class GetTaskOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, task_list_id: str, task_id: str):
        return self._gateway.get_task(task_list_id=task_list_id, task_id=task_id)
