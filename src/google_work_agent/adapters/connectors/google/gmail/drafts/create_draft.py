"""Canonical Gmail draft create connector operation."""

from __future__ import annotations

from typing import Any

from google_work_agent.ports import GoogleWorkspaceGateway


class CreateDraftOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self, *, payload: dict[str, Any], claim_context: dict[str, object] | None
    ):
        return self._gateway.create_gmail_draft(
            payload=payload, claim_context=claim_context
        )
