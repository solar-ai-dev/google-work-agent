"""Shared adjudication for non-Domain operational command replay."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.system.contracts.operational_command_replay import (
    JsonValue,
    OperationalCommandContextV1,
    OperationalReconcileResultV1,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)


class OperationalCommandConflict(RuntimeError):
    """The command identity was already reserved for different input."""


class OperationalCommandUncertain(RuntimeError):
    """The external side effect cannot currently be proven or safely retried."""


@dataclass(frozen=True, slots=True)
class OperationalReplayResult:
    operation_ref: str
    result_ref: str
    bounded_result: object
    replayed: bool


def execute_operational_command(
    *,
    replay_port: OperationalCommandReplayPort,
    command_id: str,
    operation_kind: str,
    request_payload: dict[str, object],
    reconcile: Callable[[str], OperationalReconcileResultV1],
    execute: Callable[[str], tuple[str, object]],
) -> OperationalReplayResult:
    context = OperationalCommandContextV1(
        command_id=command_id,
        operation_kind=operation_kind,
        canonical_request_hash=calculate_canonical_json_hash(request_payload),
    )
    decision = replay_port.reserve_or_replay(context)
    if decision.decision == "CONFLICT":
        raise OperationalCommandConflict("command_id already has different canonical input")
    if decision.operation_ref is None:
        raise RuntimeError("operational replay decision has no operation_ref")
    if decision.decision == "REPLAY_COMPLETED":
        if decision.stored_result_ref is None or decision.bounded_result is None:
            raise RuntimeError("completed operational replay is incomplete")
        return OperationalReplayResult(
            operation_ref=decision.operation_ref,
            result_ref=decision.stored_result_ref,
            bounded_result=decision.bounded_result,
            replayed=True,
        )
    if decision.decision == "RECOVER_RESERVED":
        recovered = reconcile(decision.operation_ref)
        if recovered.status == "UNCERTAIN":
            replay_port.mark_uncertain(
                context,
                recovered.result_ref or decision.recovery_ref or decision.operation_ref,
            )
            raise OperationalCommandUncertain("operational side effect remains uncertain")
        if recovered.status == "COMPLETED":
            if recovered.result_ref is None or recovered.bounded_result is None:
                raise RuntimeError("completed reconciliation is incomplete")
            replay_port.store_result(
                context, recovered.result_ref, cast(JsonValue, recovered.bounded_result)
            )
            return OperationalReplayResult(
                operation_ref=decision.operation_ref,
                result_ref=recovered.result_ref,
                bounded_result=cast(JsonValue, recovered.bounded_result),
                replayed=True,
            )
    result_ref, bounded_result = execute(decision.operation_ref)
    replay_port.store_result(context, result_ref, cast(JsonValue, bounded_result))
    return OperationalReplayResult(
        operation_ref=decision.operation_ref,
        result_ref=result_ref,
        bounded_result=bounded_result,
        replayed=False,
    )


__all__ = [
    "OperationalCommandConflict",
    "OperationalCommandUncertain",
    "OperationalReplayResult",
    "execute_operational_command",
]
