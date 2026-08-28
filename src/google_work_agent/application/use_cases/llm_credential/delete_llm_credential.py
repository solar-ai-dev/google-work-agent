"""Delete an LLM credential with crash-safe replay."""

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialPort, LlmCredentialStatusV1
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class DeleteLlmCredentialCommand:
    command_id: str
    provider: str


@dataclass(frozen=True, slots=True)
class DeleteLlmCredentialResult:
    status: LlmCredentialStatusV1
    operation_ref: str
    replayed: bool


class DeleteLlmCredentialHandler:
    def __init__(
        self, *, credentials: LlmCredentialPort, replay: OperationalCommandReplayPort
    ) -> None:
        self._credentials = credentials
        self._replay = replay

    def __call__(self, command: DeleteLlmCredentialCommand) -> DeleteLlmCredentialResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._credentials.delete_credential(command.provider, ref)
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="DELETE_LLM_CREDENTIAL",
            request_payload={"provider": command.provider},
            reconcile=lambda ref: self._credentials.reconcile_credential(
                ref, command.provider, "NOT_CONFIGURED"
            ),
            execute=execute,
        )
        return DeleteLlmCredentialResult(
            status=LlmCredentialStatusV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["DeleteLlmCredentialCommand", "DeleteLlmCredentialHandler", "DeleteLlmCredentialResult"]
