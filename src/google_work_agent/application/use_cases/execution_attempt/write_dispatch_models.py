"""Execution-attempt-owner values for write dispatch orchestration."""

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot


@dataclass(frozen=True, slots=True)
class PreparedWriteDispatch:
    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class AuthorizedWriteDispatch:
    prepared: PreparedWriteDispatch
    claim_context: ClaimContextV2


class WriteResultMaterializer(Protocol):
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


__all__ = ["AuthorizedWriteDispatch", "PreparedWriteDispatch", "WriteResultMaterializer"]
