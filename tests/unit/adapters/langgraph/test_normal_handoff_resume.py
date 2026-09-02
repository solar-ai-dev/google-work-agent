from threading import Lock
from types import SimpleNamespace
from typing import cast

from google_work_agent.adapters.langgraph.invocation import WorkflowInvocationCoordinator
from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowResumeRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RetrievalCacheRestartControlV1,
)


class _Graph:
    def __init__(self) -> None:
        self.calls: list[object] = []
        self.updates: list[tuple[object, str]] = []
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

    def update_state(self, _config: object, value: object, *, as_node: str) -> None:
        self.updates.append((value, as_node))


def test_normal_handoff__consumes_its_durably__materialized_target_once() -> None:
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
    assert graph.calls[0] is None


def test_cache_restart__replaces_stale__pending_retrieval_task() -> None:
    graph = _Graph()
    coordinator = _coordinator(graph)

    coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="retrieval_entry",
            normal_handoff_control=RetrievalCacheRestartControlV1(
                kind="RETRIEVAL_CACHE_RESTART",
                lost_checkpoint_id="checkpoint-1",
                lost_handle_fingerprint="a" * 64,
            ),
        )
    )

    assert graph.updates == [
        (
            {
                "workflow_phase": "CONTEXT_RETRIEVAL",
                "__logical_target__": "context_retriever",
                "__target__": "context_retriever",
                "__workflow_control__": None,
                "acquisition_result": None,
                "user_interrupt": None,
            },
            "retrieval_entry",
        )
    ]
    assert graph.calls == [None]


def test_cancel_replaces__a_preempted__user_interrupt() -> None:
    graph = _Graph()
    coordinator = _coordinator(graph)

    coordinator.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="thread-1",
            resume_kind="NORMAL_HANDOFF",
            resume_payload={},
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v2"),
            normal_handoff_target_node="cancel_resolution",
        )
    )

    assert graph.updates == [
        (
            {
                "workflow_phase": "CANCEL_RESOLUTION",
                "__logical_target__": "cancel_resolution",
                "__target__": "cancel_resolution",
                "user_interrupt": None,
            },
            "cancel_resolution",
        )
    ]
    assert graph.calls == [None]


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
