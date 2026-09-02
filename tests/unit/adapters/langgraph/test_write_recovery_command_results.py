from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.write_execution_driver import (
    WriteExecutionStructuralDriver,
)
from google_work_agent.adapters.langgraph.write_recovery import WriteRecoveryCoordinator
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.application.use_cases.run.begin_verification import BeginVerificationResult
from google_work_agent.application.use_cases.run.run_terminal import RunTransitionResponse
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1


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


def _action(status: ActionStatusV1) -> ActionRecord:
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
        status=PlanStatusV1.ACTIVE,
        summary_text="write",
        created_at_ms=1,
    )


def _action_response(*, applied: bool, status: ActionStatusV1) -> WriteActionResponse:
    return WriteActionResponse(
        applied=applied,
        result_code=(
            ResultCode.TRANSITION_APPLIED.value if applied else ResultCode.STATE_CONFLICT.value
        ),
        action_id="action-1",
        action_status=status.value,
        action_version=3,
        next_allowed_commands=(
            ("RECOVER_EXISTING_RESULT",) if status is ActionStatusV1.UNKNOWN_RESULT else ()
        ),
        attempt_id="attempt-1",
        verification_id=("verification-1" if status is ActionStatusV1.VERIFIED else None),
    )


def _completion_response(*, applied: bool, status: RunStatusV1) -> RunTransitionResponse:
    return RunTransitionResponse(
        applied=applied,
        result_code=(
            ResultCode.TRANSITION_APPLIED.value if applied else ResultCode.STATE_CONFLICT.value
        ),
        run_id="run-1",
        run_status=status.value,
        run_version=7,
        next_allowed_commands=(),
    )


def _coordinator(
    *,
    phase: _Phase,
    action: ActionRecord,
    begin_verification: Callable[[str, str, str], BeginVerificationResult | None],
    completion: Callable[[str, str], bool],
) -> WriteRecoveryCoordinator:
    return WriteRecoveryCoordinator(
        latest_unknown_action=(
            (lambda _run_id: (action, "attempt-1", 0))
            if action.status == ActionStatusV1.UNKNOWN_RESULT.value
            else (lambda _run_id: None)
        ),
        execution_phase=cast(WriteExecutionStructuralDriver, phase),
        write_run_completion_ready=completion,
        plans_for_run=lambda _run_id: (_plan(),),
        list_actions=lambda _plan_id: (action,),
        begin_verification=begin_verification,
        latest_attempt_id=lambda _action_id: "attempt-1",
    )


def test_recover_unknown_applied__false_is_never__reported_recovered_or_retried() -> None:
    action = _action(ActionStatusV1.UNKNOWN_RESULT)
    phase = _Phase(
        recover_response=_action_response(applied=False, status=ActionStatusV1.UNKNOWN_RESULT)
    )
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str) -> bool:
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run after recovery applied=false")

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id, _action_id, _attempt_id: None,
        completion=completion,
    )

    result = coordinator.recover_unknown(cast(GraphState, {"run_id": "run-1"}))

    assert cast(dict[str, object], result["__workflow_control__"])["reason"] == "DOMAIN_RECONCILE"
    assert result["__target__"] == "end"
    assert phase.recover_calls == 1
    assert completion_calls == 0


def test_begin_verification__applied_false_stops__verification_and_completion() -> None:
    action = _action(ActionStatusV1.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=True, status=ActionStatusV1.VERIFIED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str) -> bool:
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run")

    begin_conflict: BeginVerificationResult = BeginVerificationResult(
        applied=False,
        result_code=ResultCode.STATE_CONFLICT,
        current_status=RunStatusV1.RECOVERY_REQUIRED,
        current_version=5,
        next_allowed_commands=(),
        conflict_detail="already reconciled elsewhere",
    )
    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id, _action_id, _attempt_id: begin_conflict,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(GraphState, {"run_id": "run-1"}), "run-1")

    assert cast(dict[str, object], result["__workflow_control__"])["source"] == "BEGIN_VERIFICATION"
    assert phase.verify_calls == 0
    assert completion_calls == 0


def test_verification_applied__false_stops_completion__and_additional_verification() -> None:
    action = _action(ActionStatusV1.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=False, status=ActionStatusV1.EXECUTED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str) -> bool:
        nonlocal completion_calls
        completion_calls += 1
        raise AssertionError("completion must not run")

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id, _action_id, _attempt_id: None,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(GraphState, {"run_id": "run-1"}), "run-1")

    assert cast(dict[str, object], result["__workflow_control__"])["reason"] == "DOMAIN_RECONCILE"
    assert phase.verify_calls == 1
    assert completion_calls == 0


def test_completion_not__ready_is_not__reported_restart_reconciled() -> None:
    action = _action(ActionStatusV1.EXECUTED)
    phase = _Phase(verify_response=_action_response(applied=True, status=ActionStatusV1.VERIFIED))
    completion_calls = 0

    def completion(_plan_id: str, _run_id: str) -> bool:
        nonlocal completion_calls
        completion_calls += 1
        return False

    coordinator = _coordinator(
        phase=phase,
        action=action,
        begin_verification=lambda _run_id, _action_id, _attempt_id: None,
        completion=completion,
    )

    result = coordinator.recover_executed(cast(GraphState, {"run_id": "run-1"}), "run-1")

    summary = cast(dict[str, object], result["__workflow_control__"])
    assert summary["reason"] == "RECOVERY_NOT_COMPLETABLE"
    assert phase.verify_calls == 1
    assert completion_calls == 1
