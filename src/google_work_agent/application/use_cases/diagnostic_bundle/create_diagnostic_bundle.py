"""Create a bounded sanitized diagnostics bundle with operational replay."""

from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.diagnostics_port import (
    DiagnosticBundleMetadataV1,
    DiagnosticsPort,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class CreateDiagnosticBundleCommand:
    command_id: str
    scope: Literal["LAST_24H", "RUN"]
    run_id: str | None = None


@dataclass(frozen=True, slots=True)
class CreateDiagnosticBundleResult:
    bundle: DiagnosticBundleMetadataV1
    operation_ref: str
    replayed: bool


class CreateDiagnosticBundleHandler:
    def __init__(
        self, *, diagnostics: DiagnosticsPort, replay: OperationalCommandReplayPort
    ) -> None:
        self._diagnostics = diagnostics
        self._replay = replay

    def __call__(self, command: CreateDiagnosticBundleCommand) -> CreateDiagnosticBundleResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._diagnostics.create_bundle(command.scope, command.run_id, ref)
            return value.bundle_ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="CREATE_DIAGNOSTIC_BUNDLE",
            request_payload={"scope": command.scope, "run_id": command.run_id},
            reconcile=self._diagnostics.reconcile_bundle,
            execute=execute,
        )
        return CreateDiagnosticBundleResult(
            bundle=DiagnosticBundleMetadataV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = [
    "CreateDiagnosticBundleCommand",
    "CreateDiagnosticBundleHandler",
    "CreateDiagnosticBundleResult",
]
