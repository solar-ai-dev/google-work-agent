from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.write_execution import WriteExecutionNode
from google_work_agent.adapters.langgraph.write_execution_driver import (
    WriteExecutionDisposition,
    WriteExecutionPhaseResult,
)
from google_work_agent.domain.action.model import Action, ActionStatusV1


def _failed_node(*, independent_action_remains: bool) -> WriteExecutionNode:
    phase = SimpleNamespace(
        execute_claimed=lambda _request, _claim: WriteExecutionPhaseResult(
            disposition=WriteExecutionDisposition.FAILED,
            action_status=ActionStatusV1.FAILED.value,
            result_code="TRANSITION_APPLIED",
            current_version=3,
            attempt_id="attempt-1",
            delivery_certainty="NOT_SENT",
        )
    )
    return WriteExecutionNode(
        id_factory=lambda: "id-1",
        request_hash=lambda _payload: "hash",
        should_stop_for_cancel=lambda _run_id: False,
        list_actions=lambda _plan_id: (),
        has_independent_executable_action=(
            lambda _plan_id, _failed_action_id: independent_action_remains
        ),
        execute_read_only_plan=lambda state, _plan_id, _actions: state,
        execution_phase=cast(Any, phase),
        has_persisted_cancel_intent=lambda _run_id: False,
    )


def _action() -> Action:
    return Action(
        id="action-1",
        plan_id="plan-1",
        connector_id="google-workspace",
        position=1,
        tool_name="tasks_create_task",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
        target_resource_ref_id=None,
        status=ActionStatusV1.EXECUTING.value,
        arguments_json="{}",
        arguments_hash="arguments-hash",
        expected_json="{}",
        risk={},
        version=2,
        created_at_ms=1,
        updated_at_ms=2,
    )


def _state() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "__workflow_control__": {
            "stage": "PREFLIGHT_READY",
            "action_id": "action-1",
            "action_version": 1,
            "attempt_id": "attempt-1",
            "approval_id": "approval-1",
            "claimed_action_version": 2,
        },
    }


def test_not_sent_failure_continues_to_preflight_for_independent_action() -> None:
    result = _failed_node(independent_action_remains=True)._execute_action(
        state=cast(Any, _state()),
        run_id="run-1",
        plan_id="plan-1",
        action=_action(),
        verification_statuses=[],
    )

    assert result is not None
    assert result["__target__"] == "preflight"
    assert result["__logical_target__"] == "preflight"
    execution_summary = result["execution_summary"]
    workflow_control = result["__workflow_control__"]
    assert execution_summary is not None
    assert workflow_control is not None
    assert execution_summary["routing_outcome"] == "FAILED"
    assert workflow_control["reason"] == "FAILED_CONTINUE_INDEPENDENT"


def test_not_sent_failure_suspends_when_no_independent_action_remains() -> None:
    result = _failed_node(independent_action_remains=False)._execute_action(
        state=cast(Any, _state()),
        run_id="run-1",
        plan_id="plan-1",
        action=_action(),
        verification_statuses=[],
    )

    assert result is not None
    assert result["__target__"] == "end"
    assert result["__logical_target__"] == "end"
    execution_summary = result["execution_summary"]
    workflow_control = result["__workflow_control__"]
    assert execution_summary is not None
    assert workflow_control is not None
    assert execution_summary["routing_outcome"] == "FAILED"
    assert workflow_control["reason"] == "FAILED_RETRY_OR_CANCEL_REQUIRED"
