"""Restart-safe production continuation regression for corrective materialization."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.corrective_plan_reachability import (
    CorrectivePlanContinuationRequired,
)
from google_work_agent.adapters.langgraph.main.state import GraphState, ParentGraphState
from google_work_agent.adapters.langgraph.main.workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
)
from tests.support.corrective_plan_persistence import (
    _aggregate_snapshot,
    _assert_published_snapshot,
    _CorrectivePersistenceHarness,
    _persist,
    _prepare,
)


class _CountingEmptyEvidenceStore(RunScopedEvidenceStore):
    def __init__(self) -> None:
        super().__init__()
        self.resolve_calls = 0

    def resolve(
        self,
        *,
        run_id: str,
        evidence_refs: list[str],
    ) -> list[EvidenceDraftV1]:
        self.resolve_calls += 1
        return super().resolve(run_id=run_id, evidence_refs=evidence_refs)


class _RestartRuntimeHarness(_CorrectivePersistenceHarness):
    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)
        self._graph: Any = None
        self.restart_evidence_store = _CountingEmptyEvidenceStore()
        self._evidence_store = self.restart_evidence_store

    @staticmethod
    def _config_for_thread(workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    @staticmethod
    def _is_profile_compatible(_: ParentGraphState) -> bool:
        return True

    def _resume_corrective_plan(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        return LangGraphWorkflowRuntime._resume_corrective_plan(cast(Any, self), request)

    def _resume_corrective_plan_safely(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        return LangGraphWorkflowRuntime._resume_corrective_plan_safely(
            cast(Any, self),
            request,
        )

    def _result_from_thread(
        self,
        *,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(run_id)
        assert run is not None
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"run_status": run.status.value},
        )


def _compile_corrective_persistence_graph(
    *,
    connection: sqlite3.Connection,
    runtime: _CorrectivePersistenceHarness,
) -> Any:
    def persist_node(state: GraphState) -> dict[str, object]:
        draft = state["planning_result"]
        assert draft is not None
        _persist(
            runtime,
            cast(dict[str, Any], state),
            cast(dict[str, Any], draft),
        )
        return {"__reserved_corrective_plan_id__": state.get("__reserved_corrective_plan_id__")}

    builder = StateGraph(GraphState)
    builder.add_node("persist", persist_node)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)
    return builder.compile(checkpointer=SqliteSaver(connection))


def _recovery_request() -> WorkflowRecoveryRequest:
    return WorkflowRecoveryRequest(
        run_id="run-1",
        workflow_key="thread-1",
        domain_status="PLANNING",
        domain_version=6,
        correlation=WorkflowCorrelationContext(
            request_id="startup-recovery",
            command_id=None,
            api_contract_version="v1",
        ),
    )


def test_restart_after_save_commit_uses_only_durable_materialization(
    tmp_path: Path,
) -> None:
    domain_database_path = tmp_path / "corrective-restart-domain.db"
    checkpoint_database_path = tmp_path / "corrective-restart-checkpoint.db"

    # Process A owns current-run Retrieval evidence and commits Save, then the
    # Publish boundary fails. The failed graph task and reserved marker remain
    # in the checkpoint DB.
    process_a, state, draft = _prepare(
        domain_database_path,
        fail_publish_once=True,
    )
    state["planning_result"] = draft
    checkpoint_a = sqlite3.connect(
        checkpoint_database_path,
        check_same_thread=False,
    )
    try:
        graph_a = _compile_corrective_persistence_graph(
            connection=checkpoint_a,
            runtime=process_a,
        )
        config = {"configurable": {"thread_id": "thread-1"}}
        with pytest.raises(CorrectivePlanContinuationRequired):
            graph_a.invoke(state, config=config)

        failed_snapshot = graph_a.get_state(config)
        assert failed_snapshot.values["__reserved_corrective_plan_id__"] == ("reserved-plan-2")
        assert failed_snapshot.next == ("persist",)
    finally:
        checkpoint_a.close()

    after_process_a = _aggregate_snapshot(domain_database_path)
    assert after_process_a["run_status"] == "PLANNING"
    assert after_process_a["plans"][-1] == ("reserved-plan-2", 2, "DRAFT")
    assert after_process_a["trace_counts"] == {"WRITE_PLAN_SAVED": 1}
    assert process_a.save_calls == 1
    assert process_a.publish_calls == 1

    # Process B is a real fresh runtime shape: same Domain DB, same checkpoint
    # DB, but a brand-new empty RunScopedEvidenceStore. No evidence is
    # rehydrated from Domain rows or provider payloads.
    process_b = _RestartRuntimeHarness(domain_database_path)
    assert process_b.restart_evidence_store._by_run == {}
    assert process_b.restart_evidence_store.resolve_calls == 0

    checkpoint_b = sqlite3.connect(
        checkpoint_database_path,
        check_same_thread=False,
    )
    try:
        graph_b = _compile_corrective_persistence_graph(
            connection=checkpoint_b,
            runtime=process_b,
        )
        process_b._graph = graph_b

        result = LangGraphWorkflowRuntime.recover_open_run(
            cast(Any, process_b),
            _recovery_request(),
        )

        assert result.outcome is WorkflowOutcome.ACCEPTED
        assert result.payload["run_status"] == "WAITING_APPROVAL"
        final_snapshot = graph_b.get_state({"configurable": {"thread_id": "thread-1"}})
        assert final_snapshot.values["__reserved_corrective_plan_id__"] is None
        assert final_snapshot.next == ()
    finally:
        checkpoint_b.close()

    # Restart continuation must never consult transient evidence, repeat Save,
    # duplicate children, or allocate revision N+2.
    assert process_b.restart_evidence_store.resolve_calls == 0
    assert process_b.restart_evidence_store._by_run == {}
    assert process_b.save_calls == 0
    assert process_b.publish_calls == 1

    final = _aggregate_snapshot(domain_database_path)
    _assert_published_snapshot(final)
    assert final["rev3_count"] == 0
    assert len(final["new_actions"]) == 2
    assert len(final["new_evidence_ids"]) == 2
    assert final["trace_counts"] == {
        "PLAN_PUBLISHED": 1,
        "WRITE_PLAN_SAVED": 1,
    }
