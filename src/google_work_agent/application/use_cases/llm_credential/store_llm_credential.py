"""Store an LLM credential with crash-safe replay."""

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Literal, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialPort, LlmCredentialStatus
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class StoreLlmCredentialCommand:
    command_id: str
    provider: str
    secret: bytes
    storage_mode: Literal["KEYRING", "SESSION_ONLY"]


@dataclass(frozen=True, slots=True)
class StoreLlmCredentialResult:
    status: LlmCredentialStatus
    operation_ref: str
    replayed: bool


class StoreLlmCredentialHandler:
    def __init__(
        self, *, credentials: LlmCredentialPort, replay: OperationalCommandReplayPort
    ) -> None:
        self._credentials = credentials
        self._replay = replay

    def __call__(self, command: StoreLlmCredentialCommand) -> StoreLlmCredentialResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._credentials.store_credential(
                command.provider, command.secret, command.storage_mode, ref
            )
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="STORE_LLM_CREDENTIAL",
            request_payload={
                "provider": command.provider,
                "secret_sha256": sha256(command.secret).hexdigest(),
                "storage_mode": command.storage_mode,
            },
            reconcile=lambda ref: self._credentials.reconcile_credential(
                ref, command.provider, "CONFIGURED", command.storage_mode
            ),
            execute=execute,
        )
        return StoreLlmCredentialResult(
            status=LlmCredentialStatus(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["StoreLlmCredentialCommand", "StoreLlmCredentialHandler", "StoreLlmCredentialResult"]
