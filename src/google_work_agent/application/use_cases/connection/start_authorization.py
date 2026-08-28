"""Start connector OAuth authorization through the replay-protected Port."""

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.connector.oauth_credential_port import (
    AuthorizationStartV1,
    OAuthCredentialPort,
    OAuthEnvironment,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class StartAuthorizationCommand:
    command_id: str
    connector_id: str
    environment: OAuthEnvironment
    requested_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StartAuthorizationResult:
    authorization: AuthorizationStartV1
    operation_ref: str
    replayed: bool


class StartAuthorizationHandler:
    def __init__(
        self, *, credentials: OAuthCredentialPort, replay: OperationalCommandReplayPort
    ) -> None:
        self._credentials = credentials
        self._replay = replay

    def __call__(self, command: StartAuthorizationCommand) -> StartAuthorizationResult:
        def execute(operation_ref: str) -> tuple[str, dict[str, object]]:
            value = self._credentials.start_authorization(
                command.connector_id,
                command.environment,
                command.requested_scopes,
                operation_ref,
            )
            return value.callback_id, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="START_AUTHORIZATION",
            request_payload={
                "connector_id": command.connector_id,
                "environment": command.environment.value,
                "requested_scopes": list(command.requested_scopes),
            },
            reconcile=lambda ref: self._credentials.reconcile_authorization_start(
                command.connector_id, ref
            ),
            execute=execute,
        )
        return StartAuthorizationResult(
            authorization=AuthorizationStartV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["StartAuthorizationCommand", "StartAuthorizationHandler", "StartAuthorizationResult"]
