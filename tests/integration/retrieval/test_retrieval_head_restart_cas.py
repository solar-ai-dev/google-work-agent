from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TypedDict

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.system.sqlite_checkpoint import (
    CheckpointConflictError,
    SqliteCheckpointAdapter,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)


class _State(TypedDict):
    retrieval_result: dict[str, object]


def _admission() -> WorkflowExecutionAdmissionV1:
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id="admission-1",
        handoff_id="handoff-1",
        handoff_run_sequence=1,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=0,
    )


def _target() -> AgentNodeResumeTargetV2:
    return AgentNodeResumeTargetV2(
        kind="AGENT_NODE",
        semantic_owner_id="RETRIEVAL",
        compiled_subgraph_id="SIX_RETRIEVAL",
        node_id="retrieval.plan_query",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1",
    )


def _result(artifact_id: str, revision: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "meta": {"artifact_id": artifact_id, "revision": revision, "based_on": []},
    }


def test_retrieval_head__is_checkpoint_owned__and_survives_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "retrieval-head.db"
    checkpoint = SqliteCheckpointAdapter(database_path, now_ms=lambda: 10)
    builder = StateGraph(_State)
    builder.add_node("retrieval", lambda state: state)
    builder.add_edge(START, "retrieval")
    builder.add_edge("retrieval", END)
    graph = builder.compile(checkpointer=checkpoint)
    config: RunnableConfig = {"configurable": {"thread_id": "thread-1"}}

    with checkpoint.execution_scope(
        _admission(),
        applied_handoff_id="handoff-1",
        owner_scope="RETRIEVAL",
        resume_target=_target(),
    ):
        graph.invoke({"retrieval_result": _result("artifact-1", 1)}, config=config)
    first = checkpoint.load_retrieval_head("run-1")
    assert first is not None
    assert first.retrieval_revision == 1
    assert first.retrieval_artifact_id == "artifact-1"
    assert checkpoint.load_same_run_checkpoint("run-1", "thread-1") is not None
    checkpoint.close()

    reopened = SqliteCheckpointAdapter(database_path, now_ms=lambda: 20)
    try:
        assert reopened.load_retrieval_head("run-1") == first
        with pytest.raises(CheckpointConflictError, match="different artifact"):
            reopened.store_retrieval_head(replace(first, retrieval_artifact_id="tampered"))
    finally:
        reopened.close()
