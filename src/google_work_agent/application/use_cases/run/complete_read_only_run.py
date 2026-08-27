"""Canonical persisted CompleteReadOnlyRun application boundary."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.transitions.complete_read_only_run import (
    transition_complete_read_only_run,
)
from google_work_agent.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class CompleteReadOnlyRunCommand:
    command_id: str
    request_hash: str
    run_id: str
    plan_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class CompleteReadOnlyRunResult:
    applied: bool
    result_code: str
    run_id: str
    run_status: str
    run_version: int
    plan_id: str
    plan_status: str
    result_kind: str | None = None
    conflict_detail: str | None = None


class CompleteReadOnlyRunHandler:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: CompleteReadOnlyRunCommand) -> CompleteReadOnlyRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            result = self.apply_in_unit_of_work(unit_of_work, command, self._now_ms())
            unit_of_work.commit()
            return result

    @staticmethod
    def try_apply_for_parent(
        unit_of_work: UnitOfWork,
        *,
        parent_command_id: str,
        run_id: str,
        plan_id: str,
        now_ms: int,
    ) -> CompleteReadOnlyRunResult | None:
        statuses = tuple(
            ActionStatusV1(action.status) for action in unit_of_work.actions.list_by_plan(plan_id)
        )
        if not statuses or any(
            status not in {ActionStatusV1.VERIFIED, ActionStatusV1.FAILED} for status in statuses
        ):
            return None
        run = unit_of_work.runs.get(run_id)
        if run is None:
            raise LookupError(f"run not found: {run_id}")
        return CompleteReadOnlyRunHandler.apply_in_unit_of_work(
            unit_of_work,
            CompleteReadOnlyRunHandler.command_for_parent(
                parent_command_id=parent_command_id,
                run_id=run_id,
                plan_id=plan_id,
                expected_version=run.version,
            ),
            now_ms,
        )

    @staticmethod
    def apply_in_unit_of_work(
        unit_of_work: UnitOfWork,
        command: CompleteReadOnlyRunCommand,
        now_ms: int,
    ) -> CompleteReadOnlyRunResult:
        receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
        if receipt is not None:
            if receipt.request_hash != command.request_hash:
                return _current_result(
                    unit_of_work,
                    command,
                    ResultCode.DUPLICATE_COMMAND,
                    "command_id exists with a different request_hash",
                )
            if (
                receipt.response_json is not None
                and receipt.status is not CommandReceiptStatus.RECEIVED
            ):
                return CompleteReadOnlyRunResult(**loads(receipt.response_json))
            raise RuntimeError("RECEIVED CompleteReadOnlyRun receipt requires reconciliation")

        unit_of_work.command_receipts.add_received(
            command_id=command.command_id,
            command_type="CompleteReadOnlyRun",
            request_hash=command.request_hash,
            aggregate_type="Run",
            aggregate_id=command.run_id,
            created_at_ms=now_ms,
        )
        run = unit_of_work.runs.get(command.run_id)
        plan = unit_of_work.plans.get_by_id(command.plan_id)
        if run is None or plan is None or plan.run_id != run.id:
            raise LookupError("CompleteReadOnlyRun aggregate not found")
        current_plans = tuple(
            candidate
            for candidate in unit_of_work.plans.list_by_run(run.id)
            if candidate.status is not PlanStatusV1.SUPERSEDED
        )
        statuses = tuple(
            ActionStatusV1(action.status) for action in unit_of_work.actions.list_by_plan(plan.id)
        )
        if run.version != command.expected_version:
            result = _current_result(
                unit_of_work,
                command,
                ResultCode.VERSION_CONFLICT,
                "expected_version does not match current_version",
            )
        else:
            next_run, next_plan = transition_complete_read_only_run(
                run.status,
                plan_status=plan.status,
                action_statuses=statuses,
            )
            if len(current_plans) != 1 or current_plans[0].id != plan.id:
                raise RuntimeError("CompleteReadOnlyRun requires current Plan authority")
            if (
                unit_of_work.plans.update_if_status(
                    plan.id, expected_status=plan.status, next_status=next_plan
                )
                is None
            ):
                raise RuntimeError("validated CompleteReadOnlyRun Plan CAS failed")
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {
                    "status": next_run.value,
                    "version": run.version + 1,
                    "finished_at_ms": now_ms,
                },
            ):
                raise RuntimeError("validated CompleteReadOnlyRun Run CAS failed")
            result_kind = "PARTIAL" if ActionStatusV1.FAILED in statuses else "SUCCESS"
            result = CompleteReadOnlyRunResult(
                True,
                ResultCode.TRANSITION_APPLIED.value,
                run.id,
                next_run.value,
                run.version + 1,
                plan.id,
                next_plan.value,
                result_kind,
            )
            unit_of_work.audits.add(
                AuditEvent(
                    account_id=None,
                    run_id=run.id,
                    action_id=None,
                    actor_type="AGENT",
                    actor_id="complete_read_only_run",
                    actor_display="CompleteReadOnlyRun",
                    event_type="RUN_COMPLETED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata_json=dumps(
                        {
                            "command_id": command.command_id,
                            "completion_mode": "READ_ONLY",
                            "result_kind": result_kind,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
        unit_of_work.command_receipts.finish_json(
            command_id=command.command_id,
            applied=result.applied,
            result_code=ResultCode(result.result_code),
            result_version=result.run_version,
            response_json=dumps(asdict(result), sort_keys=True),
            completed_at_ms=now_ms,
        )
        return result

    @staticmethod
    def command_for_parent(
        *, parent_command_id: str, run_id: str, plan_id: str, expected_version: int
    ) -> CompleteReadOnlyRunCommand:
        payload = {"run_id": run_id, "plan_id": plan_id, "expected_version": expected_version}
        return CompleteReadOnlyRunCommand(
            command_id=f"system:complete-read-only-run:{parent_command_id}",
            request_hash=calculate_canonical_json_hash(payload),
            run_id=run_id,
            plan_id=plan_id,
            expected_version=expected_version,
        )


def _current_result(
    unit_of_work: UnitOfWork,
    command: CompleteReadOnlyRunCommand,
    code: ResultCode,
    detail: str,
) -> CompleteReadOnlyRunResult:
    run = unit_of_work.runs.get(command.run_id)
    plan = unit_of_work.plans.get_by_id(command.plan_id)
    if run is None or plan is None:
        raise LookupError("CompleteReadOnlyRun aggregate not found")
    return CompleteReadOnlyRunResult(
        False,
        code.value,
        run.id,
        run.status.value,
        run.version,
        plan.id,
        plan.status.value,
        conflict_detail=detail,
    )


__all__ = [
    "CompleteReadOnlyRunCommand",
    "CompleteReadOnlyRunHandler",
    "CompleteReadOnlyRunResult",
]
