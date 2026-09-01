from threading import Lock
from types import SimpleNamespace
from typing import cast

from langgraph.types import Command

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowResumeRequest,
)


class _Graph:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.snapshot = SimpleNamespace(
            values={"graph_profile": "SIX_ROLE_BASELINE", "graph_version": "v1"},
            next=(),
            config={"configurable": {"checkpoint_id": "before"}},
            tasks=(),
        )

    def get_state(self, _config: object) -> object:
        return self.snapshot

    def invoke(self, value: object, *, config: object) -> dict[str, object]:
        del config
        self.calls.append(value)
        self.snapshot = SimpleNamespace(
            values={
                "graph_profile": "SIX_ROLE_BASELINE",
                "graph_version": "v1",
                "workflow_phase": "PLAN_REVIEW",
            },
            next=(),
            config={"configurable": {"checkpoint_id": "after"}},
            tasks=(),
        )
        return dict(self.snapshot.values)


def test_normal_handoff_executes_its_durably_materialized_target() -> None:
    graph = _Graph()
    coordinator = _coordinator(graph)

    result = coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="review_entry",
        )
    )

    assert result.outcome == "ACCEPTED"
    assert len(graph.calls) == 1
    command = graph.calls[0]
    assert isinstance(command, Command)
    assert command.goto == "review_entry"


def _coordinator(graph: _Graph) -> WorkflowInvocationCoordinator:
    return WorkflowInvocationCoordinator(
        graph=graph,
        graph_profile=GraphProfile.SIX_ROLE_BASELINE,
        start_node="initialize",
        initial_state=lambda _request: cast(GraphState, {}),
        current_run_status=lambda _run_id: "WAITING_APPROVAL",
        latest_unknown_action=lambda _run_id: None,
        recovery_node=lambda state: state,
        has_executed_action=lambda _run_id: False,
        recover_executed_actions=lambda state, _run_id: state,
        mark_stalled_claims_as_unknown=lambda _run_id: False,
        cancel_signal_lock=Lock(),
        cancel_signals=set(),
    )
