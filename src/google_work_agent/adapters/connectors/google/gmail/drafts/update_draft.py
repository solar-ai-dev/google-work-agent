"""Canonical Gmail draft update connector operation."""

from __future__ import annotations

from typing import Any

from google_work_agent.ports import GoogleWorkspaceGateway


class UpdateDraftOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        draft_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, object] | None,
    ):
        return self._gateway.update_gmail_draft(
            draft_id=draft_id, payload=payload, claim_context=claim_context
        )
