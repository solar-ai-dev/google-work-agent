"""Canonical Google Tasks update connector operation."""

from __future__ import annotations

from typing import Any

from google_work_agent.ports import GoogleWorkspaceGateway


class UpdateTaskOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        task_list_id: str,
        task_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, object] | None,
    ):
        return self._gateway.update_task(
            task_list_id=task_list_id,
            task_id=task_id,
            payload=payload,
            claim_context=claim_context,
        )
