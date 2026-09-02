from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.write_execution import WriteExecutionNode
from google_work_agent.adapters.langgraph.write_execution_driver import (
    WriteExecutionDisposition,
    WriteExecutionPhaseResult,
)
from google_work_agent.domain.action.model import Action, ActionStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)


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


def test_not_sent_failure__continues_to_preflight__for_independent_action() -> None:
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


def test_not_sent_failure__suspends_when_no__independent_action_remains() -> None:
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


def test_read_plan_uses__legacy_read_authority__without_write_driver() -> None:
    calls: list[str] = []
    read_action = replace(
        _action(),
        effect_type="READ",
        status=ActionStatusV1.PROPOSED.value,
    )
    phase = SimpleNamespace(
        execute_claimed=lambda *_args: (_ for _ in ()).throw(
            AssertionError("READ must not enter Write execution")
        )
    )
    node = WriteExecutionNode(
        id_factory=lambda: "id-1",
        request_hash=lambda _payload: "hash",
        should_stop_for_cancel=lambda _run_id: False,
        list_actions=lambda _plan_id: (read_action,),
        has_independent_executable_action=lambda _plan_id, _action_id: False,
        execution_phase=cast(Any, phase),
        has_persisted_cancel_intent=lambda _run_id: False,
        execute_read_only_plan=lambda state, plan_id, actions: cast(
            Any,
            {
                **state,
                "__target__": "response_synthesis",
                "plan_id": plan_id,
                "action_ids": [action.id for action in actions],
            },
        ),
    )
    state = cast(
        Any,
        {
            "run_id": "run-1",
            "approved_plan_id": "plan-1",
        },
    )

    result = node(state)
    result_payload = cast(dict[str, Any], result)

    calls.append(cast(str, result["__target__"]))
    assert calls == ["response_synthesis"]
    assert result_payload["plan_id"] == "plan-1"
    assert result_payload["action_ids"] == ["action-1"]


def test_cancelled_read_plan__stops_before_read__or_write_execution() -> None:
    read_called = False
    read_action = replace(_action(), effect_type="READ")

    def execute_read(*_args: object) -> Any:
        nonlocal read_called
        read_called = True
        return {}

    node = WriteExecutionNode(
        id_factory=lambda: "id-1",
        request_hash=lambda _payload: "hash",
        should_stop_for_cancel=lambda _run_id: True,
        list_actions=lambda _plan_id: (read_action,),
        has_independent_executable_action=lambda _plan_id, _action_id: False,
        execution_phase=cast(Any, SimpleNamespace()),
        has_persisted_cancel_intent=lambda _run_id: True,
        execute_read_only_plan=execute_read,
    )

    result = node(cast(Any, {"run_id": "run-1", "approved_plan_id": "plan-1"}))

    assert result["__target__"] == "cancel_resolution"
    assert read_called is False


def test_verified_and_rejected__write_actions_route__to_partial_terminal_synthesis() -> None:
    verified = replace(_action(), status=ActionStatusV1.VERIFIED.value)
    rejected = replace(
        _action(),
        id="action-2",
        position=2,
        status=ActionStatusV1.REJECTED.value,
    )
    node = WriteExecutionNode(
        id_factory=lambda: "id-1",
        request_hash=lambda _payload: "hash",
        should_stop_for_cancel=lambda _run_id: False,
        list_actions=lambda _plan_id: (verified, rejected),
        has_independent_executable_action=lambda _plan_id, _action_id: False,
        execution_phase=cast(Any, SimpleNamespace()),
        has_persisted_cancel_intent=lambda _run_id: False,
    )

    result = node(cast(Any, {"run_id": "run-1", "approved_plan_id": "plan-1"}))

    assert result["__target__"] == "response_synthesis"
    control = cast(dict[str, object], result["__workflow_control__"])
    assert control["action_statuses"] == ["VERIFIED", "REJECTED"]


def test_preflight_routes_closed__partial_plan_to__terminal_action_reconciliation() -> None:
    verified = replace(_action(), status=ActionStatusV1.VERIFIED.value)
    rejected = replace(_action(), id="action-2", status=ActionStatusV1.REJECTED.value)
    node = WriteExecutionNode(
        id_factory=lambda: "id-1",
        request_hash=lambda _payload: "hash",
        should_stop_for_cancel=lambda _run_id: False,
        list_actions=lambda _plan_id: (verified, rejected),
        has_independent_executable_action=lambda _plan_id, _action_id: False,
        execution_phase=cast(Any, SimpleNamespace()),
        has_persisted_cancel_intent=lambda _run_id: False,
    )

    result = node.preflight({"run_id": "run-1", "approved_plan_id": "plan-1"})

    assert result["__target__"] == "action_execution"
    assert result["__logical_target__"] == "action_execution"


def test_read_gateway__failure_is_settled__before_terminal_projection() -> None:
    failed_commands: list[object] = []
    proposed = replace(
        _action(),
        effect_type="READ",
        status=ActionStatusV1.PROPOSED.value,
        version=0,
    )
    failed = replace(proposed, status=ActionStatusV1.FAILED.value, version=2)
    runtime = SimpleNamespace(
        _should_stop_for_cancel=lambda _run_id: False,
        _id_factory=lambda: "command-1",
        _request_hash=lambda _payload: "hash",
        _claim_read=lambda _command: SimpleNamespace(applied=True, action_version=1),
        _execute_read=lambda **_kwargs: (_ for _ in ()).throw(
            GoogleWorkspaceGatewayError(
                code=GoogleWorkspaceErrorCode.TIMEOUT,
                message="read timeout",
                delivered=False,
                mutated=False,
            )
        ),
        _fail_read=lambda command: failed_commands.append(command),
        _complete_read=lambda _command: None,
        _finalize_read=lambda _command: None,
        _list_actions=lambda _plan_id: (failed,),
    )

    result = LangGraphWorkflowRuntime._execute_read_only_plan(
        cast(Any, runtime),
        cast(Any, {"run_id": "run-1"}),
        "plan-1",
        (proposed,),
    )

    assert len(failed_commands) == 1
    assert result["__target__"] == "response_synthesis"
