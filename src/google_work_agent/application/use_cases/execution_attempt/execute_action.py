"""Dispatch one already-claimed write through the connector execution port."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from json import loads

from google_work_agent.application.ports import ConnectorExecutionPort, ConnectorWriteRequest
from google_work_agent.application.write_action_arguments import coerce_int
from google_work_agent.application.write_execution_integrity import read_claim_token
from google_work_agent.application.write_persistence import (
    require_action,
    require_approval,
    require_attempt,
    require_plan,
    require_run,
)
from google_work_agent.domain import ExecutionAttemptStatus, RunStatus, calculate_canonical_json_hash
from google_work_agent.ports import ResourceSnapshot, UnitOfWork


@dataclass(frozen=True, slots=True)
class ExecuteActionCommand:
    action_id: str
    claim_token: str


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
        connector_execution: ConnectorExecutionPort,
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._connector_execution = connector_execution
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
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

        nonce = str(payload["nonce"])
        with self._nonce_lock:
            if nonce in self._used_nonces:
                raise PermissionError("claim token has already been used")
            self._used_nonces.add(nonce)

        try:
            with self._unit_of_work_factory() as unit_of_work:
                action = require_action(unit_of_work, action_id)
                plan = require_plan(unit_of_work, action.plan_id)
                run = require_run(unit_of_work, plan.run_id)
                approval = require_approval(unit_of_work, str(payload["approval_id"]))
                attempt = require_attempt(unit_of_work, str(payload["attempt_id"]))
                if run.status in {RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED}:
                    raise PermissionError("run cancellation forbids write dispatch")
                if action.id != str(payload["action_id"]) or action.tool_name != str(payload["tool_name"]):
                    raise PermissionError("claim token action/tool binding mismatch")
                if action.arguments_hash != str(payload["arguments_hash"]):
                    raise PermissionError("claim token arguments binding mismatch")
                if approval.action_id != action.id or attempt.approval_id != approval.id:
                    raise PermissionError("claim token persistence binding mismatch")
                if attempt.status is not ExecutionAttemptStatus.CLAIMED:
                    raise PermissionError("execution attempt is not CLAIMED")
        except Exception:
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
        return ExecuteActionResult(snapshot=snapshot, response_metadata_json="")
