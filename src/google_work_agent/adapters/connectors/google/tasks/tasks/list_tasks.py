"""Canonical Google Tasks list connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class ListTasksOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, task_list_id: str, page_token: str | None, page_size: int):
        return self._gateway.list_tasks(
            task_list_id=task_list_id, page_token=page_token, page_size=page_size
        )
