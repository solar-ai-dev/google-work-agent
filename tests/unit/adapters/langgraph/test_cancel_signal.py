from threading import Lock
from typing import cast

from google_work_agent.adapters.langgraph.main.workflow import GraphState, LangGraphWorkflowRuntime
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCancelRequest,
    WorkflowOutcome,
)


def test_cancel_signal_routes_the_next_graph_edge_to_end() -> None:
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
    assert runtime._route_next_node(state) == "end"
