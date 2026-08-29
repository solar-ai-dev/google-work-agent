"""Test-only historical claimed-write dispatch."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.write_action_arguments import coerce_int
from google_work_agent.application.use_cases.claim.build_claim_context import ClaimContextV2
from google_work_agent.application.use_cases.claim.write_execution_integrity import read_claim_token
from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptCommand,
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    AuthorizedWriteDispatch,
    WriteResultMaterializer,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.connector.contracts.google_workspace import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ExecuteActionCommand:
    action_id: str
    claim_token: str
    attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecuteActionResult:
    snapshot: ResourceSnapshot
    response_metadata_json: str


class ExecuteActionHandler:
    """Execute a claimed action; this handler never creates or acquires a claim."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        connector_execution: WriteResultMaterializer,
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._begin_execution_attempt = BeginExecutionAttemptHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._used_nonces: set[str] = set()
        self._nonce_lock = threading.Lock()

    def __call__(self, command: ExecuteActionCommand) -> ExecuteActionResult:
        action_id = command.action_id
        claim_token = command.claim_token
        payload = read_claim_token(claim_token, signing_secret=self._signing_secret)
        if str(payload["service_instance_id"]) != self._service_instance_id:
            raise PermissionError("claim token service binding mismatch")
        if self._now_ms() >= coerce_int(payload["expires_at_ms"]):
            raise PermissionError("claim token has expired")
        payload_attempt_id = str(payload["attempt_id"])
        if command.attempt_id is not None and command.attempt_id != payload_attempt_id:
            raise PermissionError("claim token attempt binding mismatch")

        nonce = str(payload["nonce"])
        with self._nonce_lock:
            if nonce in self._used_nonces:
                raise PermissionError("claim token has already been used")
            self._used_nonces.add(nonce)

        try:
            begun = self._begin_execution_attempt(
                BeginExecutionAttemptCommand(
                    command_id=f"begin-execution-attempt:{payload['attempt_id']}",
                    request_hash=calculate_canonical_json_hash(payload),
                    action_id=action_id,
                    claim_payload=payload,
                )
            )
            action = begun.action
            approval = begun.approval
        except Exception:
            # No connector dispatch occurred. Releasing the reserved nonce keeps a
            # legitimate resume possible without weakening single-use after dispatch.
            with self._nonce_lock:
                self._used_nonces.discard(nonce)
            raise

        prepared = self._connector_execution.prepare_write(
            tool_name=action.tool_name,
            arguments=loads(action.arguments_json),
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        snapshot = self._connector_execution.execute_write(
            AuthorizedWriteDispatch(
                prepared=prepared,
                claim_context=_legacy_claim_context(
                    payload,
                    execution_arguments_hash=calculate_canonical_json_hash(prepared.arguments),
                ),
            )
        )
        return ExecuteActionResult(
            snapshot=snapshot,
            response_metadata_json=dumps(
                {"operation": action.tool_name, "resource_id": snapshot.resource_id},
                sort_keys=True,
            ),
        )


def _legacy_claim_context(
    payload: dict[str, object], *, execution_arguments_hash: str
) -> ClaimContextV2:
    return ClaimContextV2(
        claim_version=2,
        service_instance_id=str(payload["service_instance_id"]),
        mcp_process_instance_id="test-legacy-mcp",
        action_id=str(payload["action_id"]),
        approval_id=str(payload["approval_id"]),
        execution_attempt_id=str(payload["execution_attempt_id"]),
        tool_name=str(payload["tool_name"]),
        approval_arguments_hash=str(payload["approval_arguments_hash"]),
        execution_arguments_hash=execution_arguments_hash,
        issued_at_ms=int(payload["issued_at_ms"]),
        expires_at_ms=int(payload["expires_at_ms"]),
        nonce=str(payload["nonce"]),
        signature="test-legacy-signature",
    )


def classify_write_delivery(error: GoogleWorkspaceGatewayError) -> DeliveryCertainty:
    """Preserve the connector's dispatch certainty without guessing from HTTP status."""

    return error.delivery_certainty


def calculate_write_failure_result_code(error: GoogleWorkspaceGatewayError) -> ResultCode:
    """Only a proven NOT_SENT failure may enter the ordinary FAILED path."""

    return (
        ResultCode.STATE_CONFLICT
        if classify_write_delivery(error) is DeliveryCertainty.NOT_SENT
        else ResultCode.RECOVERY_REQUIRED
    )


def is_reauth_required_error(error: GoogleWorkspaceGatewayError) -> bool:
    """Identify credential expiry without converting it into a retry decision."""

    return error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
