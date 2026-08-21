"""Canonical Google Tasks create connector operation."""

from __future__ import annotations

from typing import Any

from google_work_agent.ports import GoogleWorkspaceGateway


class CreateTaskOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        task_list_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, object] | None,
    ):
        return self._gateway.create_task(
            task_list_id=task_list_id, payload=payload, claim_context=claim_context
        )
