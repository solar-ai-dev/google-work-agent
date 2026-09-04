from pathlib import Path

from google_work_agent.adapters.system.sqlite_checkpoint import (
    SqliteCheckpointAdapter,
    _retrieval_requirements_from_checkpoint,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)


def test_retrieval_cache__requirements_project__only_bounded_bindings() -> None:
    requirements = _retrieval_requirements_from_checkpoint(
        {
            "channel_values": {
                "__context_read_result_handles__": ["read-1", "read-1"],
                "__context_read_bindings__": {
                    "read-1": {
                        "route_id": "route-1",
                        "query_identity_hash": "a" * 64,
                        "raw_result": "must-not-project",
                    }
                },
            }
        }
    )

    assert requirements is not None
    assert len(requirements) == 1
    assert requirements[0].read_result_handle == "read-1"
    assert requirements[0].route_id == "route-1"
    assert requirements[0].query_identity_hash == "a" * 64


def test_nested_retrieval__requirements_overlay_latest__root_resume_checkpoint(
    tmp_path: Path,
) -> None:
    checkpoint = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 10)
    admission = WorkflowExecutionAdmissionV1(
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
    target = MainControlResumeTargetV2(
        kind="MAIN_CONTROL",
        stage_id="RETRIEVAL_ENTRY",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="v1",
    )
    base_checkpoint = {
        "v": 4,
        "ts": "2026-09-04T00:00:00+00:00",
        "channel_versions": {},
        "versions_seen": {},
        "updated_channels": [],
    }

    try:
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id="handoff-1",
            owner_scope="RETRIEVAL",
            resume_target=target,
        ):
            checkpoint.put(
                {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}},
                {**base_checkpoint, "id": "root-1", "channel_values": {}},
                {},
                {},
            )
            checkpoint.put(
                {
                    "configurable": {
                        "thread_id": "thread-1",
                        "checkpoint_ns": "context_retriever:task-1",
                    }
                },
                {
                    **base_checkpoint,
                    "id": "nested-1",
                    "channel_values": {
                        "__context_read_result_handles__": ["read-1"],
                        "__context_read_bindings__": {
                            "read-1": {
                                "route_id": "route-1",
                                "query_identity_hash": "a" * 64,
                            }
                        },
                    },
                },
                {},
                {},
            )

        loaded = checkpoint.load_same_run_checkpoint("run-1", "thread-1")
    finally:
        checkpoint.close()

    assert loaded is not None
    assert loaded.checkpoint_id == "root-1"
    assert loaded.checkpoint_generation == 1
    assert len(loaded.retrieval_cache_requirements) == 1
    assert loaded.retrieval_cache_requirements[0].read_result_handle == "read-1"
