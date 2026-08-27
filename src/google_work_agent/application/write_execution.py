"""Claim-bound external execution of write actions."""

from __future__ import annotations

import threading
from collections.abc import Callable
from json import dumps, loads

from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptCommand,
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.write_action_arguments import coerce_int as _coerce_int
from google_work_agent.application.write_execution_contracts import ExecutedWriteActionResult
from google_work_agent.application.write_execution_integrity import read_claim_token
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    UnitOfWork,
)
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
    ConnectorWriteRequest,
)


class ExecuteWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        gateway: ConnectorWritePort,
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = gateway
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._begin_execution_attempt = BeginExecutionAttemptHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._used_nonces: set[str] = set()
        self._nonce_lock = threading.Lock()

    def __call__(self, *, action_id: str, claim_token: str) -> ExecutedWriteActionResult:
        payload = read_claim_token(claim_token, signing_secret=self._signing_secret)
        if str(payload["service_instance_id"]) != self._service_instance_id:
            raise PermissionError("claim token service binding mismatch")
        if self._now_ms() >= _coerce_int(payload["expires_at_ms"]):
            raise PermissionError("claim token has expired")
        nonce = str(payload["nonce"])
        # Atomically check-and-reserve the nonce before doing anything else so
        # two concurrent callers holding the same claim token can never both
        # pass this gate, regardless of what happens to either request next.
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
            # Nothing was dispatched: release the nonce so a legitimate retry
            # of this same claim token (e.g. a langgraph resume that re-runs
            # execution after a transient pre-dispatch validation failure) is
            # not permanently blocked by a claim that never reached Google.
            with self._nonce_lock:
                self._used_nonces.discard(nonce)
            raise

        prepared = self._connector_execution.prepare_write(
            tool_name=action.tool_name,
            arguments=loads(action.arguments_json),
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        snapshot = self._connector_execution.execute_write(
            ConnectorWriteRequest(
                prepared=prepared,
                claim_payload=payload,
                approval_arguments_hash=action.arguments_hash,
                execution_arguments_hash=calculate_canonical_json_hash(prepared.arguments),
            )
        )
        return ExecutedWriteActionResult(
            snapshot=snapshot,
            response_metadata_json=dumps(
                {"operation": action.tool_name, "resource_id": snapshot.resource_id},
                sort_keys=True,
            ),
        )


def classify_write_delivery(error: GoogleWorkspaceGatewayError) -> DeliveryCertainty:
    return error.delivery_certainty


def calculate_write_failure_result_code(error: GoogleWorkspaceGatewayError) -> ResultCode:
    return (
        ResultCode.RECOVERY_REQUIRED
        if classify_write_delivery(error) is not DeliveryCertainty.NOT_SENT
        else ResultCode.STATE_CONFLICT
    )


def is_reauth_required_error(error: GoogleWorkspaceGatewayError) -> bool:
    return error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
