"""Connector execution capabilities required by write safety services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.ports import ResourceSnapshot


@dataclass(frozen=True, slots=True)
class PreparedConnectorWrite:
    """Exact provider arguments whose hash is bound into ClaimContextV2."""

    tool_name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ConnectorWriteRequest:
    """A safety-authorized write request ready for provider dispatch."""

    prepared: PreparedConnectorWrite
    claim_payload: dict[str, object]
    approval_arguments_hash: str
    execution_arguments_hash: str


class ConnectorExecutionPort(Protocol):
    """Provider execution and lookup mechanics without safety policy ownership."""

    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedConnectorWrite: ...

    def execute_write(self, request: ConnectorWriteRequest) -> ResourceSnapshot: ...

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot: ...

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]: ...
