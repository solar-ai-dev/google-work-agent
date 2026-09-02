from threading import Lock
from typing import cast

from google_work_agent.adapters.langgraph.main.routing.route_after_action_execution import (
    route_after_action_execution,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_stage_three import (
    route_after_stage_three,
)
from google_work_agent.adapters.langgraph.main.workflow import GraphState, LangGraphWorkflowRuntime
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCancelRequest,
    WorkflowOutcome,
)


def test_cancel_signal_routes__the_next_graph__edge_to_end() -> None:
    runtime = object.__new__(LangGraphWorkflowRuntime)
    runtime._cancel_signal_lock = Lock()
    runtime._cancel_signals = set()

    result = runtime.request_cancel(
        WorkflowCancelRequest(
            run_id="run-1",
            workflow_key="thread-1",
            reason_code="user_requested",
        )
    )

    assert result.outcome is WorkflowOutcome.ACCEPTED
    state = cast(GraphState, {"run_id": "run-1", "__target__": "action_execution"})
    assert (
        route_after_action_execution(
            state,
            should_stop_for_cancel=runtime._should_stop_for_cancel,
        )
        == "end"
    )


def test_pending_review_settlement__runs_only_after__review_output_exists() -> None:
    control = {
        "schema_version": 1,
        "stage": "REVIEW_PENDING_SETTLEMENT",
    }

    assert (
        route_after_stage_three(
            cast(
                GraphState,
                {
                    "__target__": "stage_three",
                    "__workflow_control__": control,
                },
            ),
            available_targets={"stage_three", "review_entry", "waiting_approval", "end"},
            should_stop_for_cancel=lambda _run_id: False,
        )
        == "stage_three"
    )
    assert (
        route_after_stage_three(
            cast(
                GraphState,
                {
                    "__target__": "waiting_approval",
                    "__workflow_control__": control,
                    "plan_review": {"status": "PASS"},
                },
            ),
            available_targets={"stage_three", "review_entry", "waiting_approval", "end"},
            should_stop_for_cancel=lambda _run_id: False,
        )
        == "review_entry"
    )
