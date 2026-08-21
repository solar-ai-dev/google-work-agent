"""Canonical Gmail send connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class SendMessageOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        *,
        draft_id: str,
        recovery_fingerprint: str | None,
        claim_context: dict[str, object] | None,
    ):
        return self._gateway.send_gmail(
            draft_id=draft_id,
            recovery_fingerprint=recovery_fingerprint,
            claim_context=claim_context,
        )
