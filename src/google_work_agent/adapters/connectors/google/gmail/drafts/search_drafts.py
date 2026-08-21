"""Canonical Gmail draft recovery-search connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway, ResourceType


class SearchDraftsOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, recovery_fingerprint: str):
        return self._gateway.search_by_recovery_fingerprint(
            resource_type=ResourceType.GMAIL_DRAFT,
            recovery_fingerprint=recovery_fingerprint,
        )
