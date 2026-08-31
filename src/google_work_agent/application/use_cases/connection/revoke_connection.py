"""Revoke connector credentials through crash-safe operational replay."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.connector.connected_account_store import ConnectedAccountStore
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthCredentialPort,
    RevokeResultV1,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


@dataclass(frozen=True, slots=True)
class RevokeConnectionCommand:
    command_id: str
    connector_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class RevokeConnectionResult:
    revocation: RevokeResultV1
    operation_ref: str
    replayed: bool


class RevokeConnectionHandler:
    def __init__(
        self,
        *,
        credentials: OAuthCredentialPort,
        replay: OperationalCommandReplayPort,
        connected_account_store_factory: Callable[
            [], AbstractContextManager[ConnectedAccountStore]
        ],
        now_ms: Callable[[], int],
    ) -> None:
        self._credentials = credentials
        self._replay = replay
        self._connected_account_store_factory = connected_account_store_factory
        self._now_ms = now_ms

    def __call__(self, command: RevokeConnectionCommand) -> RevokeConnectionResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._credentials.revoke_connection(
                command.connector_id, command.account_id, ref
            )
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="REVOKE_CONNECTION",
            request_payload={
                "connector_id": command.connector_id,
                "account_id": command.account_id,
            },
            reconcile=lambda ref: self._credentials.reconcile_revoke_connection(
                command.connector_id, command.account_id, ref
            ),
            execute=execute,
        )
        with self._connected_account_store_factory() as store:
            if not store.disconnect(
                account_id=command.account_id,
                disconnected_at_ms=self._now_ms(),
            ):
                raise LookupError(f"connected account not found: {command.account_id}")
        return RevokeConnectionResult(
            revocation=RevokeResultV1(**cast(Any, outcome.bounded_result)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["RevokeConnectionCommand", "RevokeConnectionHandler", "RevokeConnectionResult"]
