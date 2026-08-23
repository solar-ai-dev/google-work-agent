from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.write_recovery import WriteRecoveryCoordinator
from google_work_agent.application.execution_phase import WriteExecutionPhaseCoordinator
from google_work_agent.application.run_terminal import RunTransitionResponse
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.domain import (
    ActionStatus,
    CommandResult,
    ResultCode,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports import ActionRecord, PlanRecord, PlanStatus


class _Phase:
    def __init__(
        self,
        *,
        recover_response: WriteActionResponse | None = None,
        verify_response: WriteActionResponse | None = None,
    ) -> None:
        self.recover_response = recover_response
        self.verify_response = verify_response
        self.recover_calls = 0
        self.verify_calls = 0

    def recover_unknown(self, _request: object) -> WriteActionResponse:
        self.recover_calls += 1
        assert self.recover_response is not None
        return self.recover_response

    def verify_executed(self, **_kwargs: object) -> WriteActionResponse:
        self.verify_calls += 1
        assert self.verify_response is not None
        return self.verify_response


def _action(status: ActionStatus) -> ActionRecord:
    return ActionRecord(
        id="action-1",
        plan_id="plan-1",
        connector_id="google_workspace",
        position=0,
        tool_name="tasks_create_task",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
        target_resource_ref_id=None,
        status=status.value,
        arguments_json="{}",
        arguments_hash="hash",
        expected_json="{}",
        risk={},
        version=3,
        created_at_ms=1,
        updated_at_ms=1,
    )


def _plan() -> PlanRecord:
    return PlanRecord(
        id="plan-1",
        run_id="run-1",
        revision_no=1,
        status=PlanStatus.ACTIVE,
        summary_text="write",
        created_at_ms=1,
    )


def _action_response(*, applied: bool, status: ActionStatus) -> WriteActionResponse:
    return WriteActionResponse(
        applied=applied,
        result_code=(
            ResultCode.TRANSITION_APPLIED.value if applied else ResultCode.STATE_CONFLICT.value
        ),
        action_id="action-1",
        action_status=status.value,
        action_version=3,
        next_allowed_commands=(
            ("RECOVER_EXISTING_RESULT",) if status is ActionStatus.UNKNOWN_RESULT else ()
        ),
        attempt_id="attempt-1",
    )


def _completion_response(*, applied: bool, status: RunStatus) -> RunTransitionResponse:
    return RunTransitionResponse(
        applied=applied,
        result_code=(
            ResultCode.TRANSITION_APPLIED.value if applied else ResultCode.STATE_CONFLICT.value
        ),
        run_id="run-1",
        run_status=status.value,
        run_version=7,
        next_allowed_commands=(
            (RunCommand.RESOLVE_RECOVERY.value,) if status is RunStatus.RECOVERY_REQUIRED else ()
        ),
    )


def _coordinator(
    *,
    phase: _Phase,
    action: ActionRecord,
    begin_verification,
    completion,
) -> WriteRecoveryCoordinator:
    return WriteRecoveryCoordinator(
        latest_unknown_action=(
            (lambda _run_id: (action, "attempt-1", 0))
            if action.status == ActionStatus.UNKNOWN_RESULT.value
            else (lambda _run_id: None)
        ),
        execution_phase=cast(WriteExecutionPhaseCoordinator, phase),
        complete_write_run_if_verified=completion,
        plans_for_run=lambda _run_id: (_plan(),),
        list_actions=lambda _plan_id: (action,),
        begin_verification=begin_verification,
        latest_attempt_id=lambda _action_id: "attempt-1",
    )


def test_recover_unknown_applied_false_is_never_reported_recovered_or_retried() -> None:
    action = _action(ActionStatus.UNKNOWN_RESULT)
    phase = _Phase(recover_response=_action_response(applied=False, status=ActionStatus.UNKNOWN_RESULT))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str):
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run after recovery applied=false")

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id: None,
        completion=completion,
    )

    result = coordinator.recover_unknown(cast(dict, {"run_id": "run-1"}))

    assert cast(dict, result["execution_summary"])["result"] == "DOMAIN_RECONCILE"
    assert result["__target__"] == "end"
    assert phase.recover_calls == 1
    assert completion_calls == 0


def test_begin_verification_applied_false_stops_verification_and_completion() -> None:
    action = _action(ActionStatus.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=True, status=ActionStatus.VERIFIED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str):
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run")

    begin_conflict = CommandResult(
        applied=False,
        result_code=ResultCode.STATE_CONFLICT,
        current_status=RunStatus.RECOVERY_REQUIRED,
        current_version=5,
        next_allowed_commands=(RunCommand.RESOLVE_RECOVERY,),
        conflict_detail="already reconciled elsewhere",
    )
    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id: begin_conflict,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(dict, {"run_id": "run-1"}), "run-1")

    assert cast(dict, result["execution_summary"])["source"] == "BEGIN_VERIFICATION"
    assert phase.verify_calls == 0
    assert completion_calls == 0


def test_verification_applied_false_stops_completion_and_additional_verification() -> None:
    action = _action(ActionStatus.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=False, status=ActionStatus.EXECUTED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str):
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run")

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id: None,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(dict, {"run_id": "run-1"}), "run-1")

    assert cast(dict, result["execution_summary"])["result"] == "DOMAIN_RECONCILE"
    assert phase.verify_calls == 1
    assert completion_calls == 0


def test_completion_applied_false_is_not_reported_restart_reconciled() -> None:
    action = _action(ActionStatus.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=True, status=ActionStatus.VERIFIED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str) -> RunTransitionResponse:
        nonlocal completion_calls
        completion_calls += 1
        return _completion_response(applied=False, status=RunStatus.RECOVERY_REQUIRED)

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id: None,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(dict, {"run_id": "run-1"}), "run-1")

    summary = cast(dict, result["execution_summary"])
    assert summary["result"] == "DOMAIN_RECONCILE"
    assert summary["result"] != "RESTART_RECONCILED"
    assert phase.verify_calls == 1
    assert completion_calls == 1
