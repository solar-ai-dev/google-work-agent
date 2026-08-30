"""Test-only contract for the pre-canonical write helpers."""

from typing import Protocol

from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    AuthorizedWriteDispatch,
    PreparedWriteDispatch,
)
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


class LegacyWriteResultMaterializer(Protocol):
    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedWriteDispatch: ...

    def execute_write(self, request: AuthorizedWriteDispatch) -> ResourceSnapshot: ...

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot: ...

    def search_recovery_candidates(
        self, *, tool_name: str, recovery_fingerprint: str
    ) -> tuple[ResourceSnapshot, ...]: ...


__all__ = ["LegacyWriteResultMaterializer"]
