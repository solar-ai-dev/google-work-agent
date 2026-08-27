"""Sanitized diagnostics bundle boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)


@dataclass(frozen=True, slots=True)
class DiagnosticBundleMetadataV1:
    schema_version: Literal[1]
    bundle_ref: str
    scope: Literal["LAST_24H", "RUN"]
    created_at_ms: int
    size_bytes: int


class DiagnosticsPort(Protocol):
    def create_bundle(
        self,
        scope: Literal["LAST_24H", "RUN"],
        run_id: str | None,
        operation_ref: str,
    ) -> DiagnosticBundleMetadataV1: ...

    def reconcile_bundle(self, operation_ref: str) -> OperationalReconcileResultV1: ...


__all__ = ["DiagnosticBundleMetadataV1", "DiagnosticsPort"]
