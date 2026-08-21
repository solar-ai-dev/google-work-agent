"""Canonical Gmail thread search connector operation."""

from __future__ import annotations

from google_work_agent.ports import GoogleWorkspaceGateway


class SearchThreadsOperation:
    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def execute(self, *, query: str, page_token: str | None, page_size: int):
        return self._gateway.search_gmail_threads(
            query=query, page_token=page_token, page_size=page_size
        )
