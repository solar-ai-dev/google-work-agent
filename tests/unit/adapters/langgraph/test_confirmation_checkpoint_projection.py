from types import SimpleNamespace
from typing import cast

from google_work_agent.adapters.langgraph.main.resume_checkpoint import ResumeCheckpointMixin
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


def test_pending_confirmation__after_restart__uses_bubbled_main_task() -> None:
    target = AgentNodeResumeTargetV2(
        kind="AGENT_NODE",
        semantic_owner_id="REQUEST_UNDERSTANDING",
        compiled_subgraph_id="SIX_REQUEST_UNDERSTANDING",
        node_id="request.finalize",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
    )
    interrupt = {
        "interrupt_kind": "CONFIRMATION",
        "interrupt_id": "interrupt-1",
        "semantic_owner_id": "REQUEST_UNDERSTANDING",
        "resume_target": {
            "kind": target.kind,
            "semantic_owner_id": target.semantic_owner_id,
            "compiled_subgraph_id": target.compiled_subgraph_id,
            "node_id": target.node_id,
            "graph_profile": target.graph_profile,
            "graph_version": target.graph_version,
        },
        "pre_confirmation_status": "ANALYZING",
        "question": "Please clarify recipient",
        "options": [],
    }
    snapshot = SimpleNamespace(
        interrupts=(),
        tasks=(
            SimpleNamespace(
                interrupts=(SimpleNamespace(value=interrupt),),
                state=None,
            ),
        ),
    )

    class _Graph:
        def get_state(self, config: dict[str, object]) -> SimpleNamespace:
            assert config == {"configurable": {"thread_id": "workflow-1"}}
            return snapshot

    class _CheckpointPort:
        @staticmethod
        def load_workflow_binding(run_id: str) -> WorkflowBindingV1:
            assert run_id == "run-1"
            return WorkflowBindingV1(
                schema_version=1,
                workflow_key="workflow-1",
                run_id=run_id,
                langgraph_thread_id="thread-1",
                graph_profile="SIX_ROLE_BASELINE",
                graph_version="resume-contract-v1",
                requested_mode="LOCAL_GPU",
                created_at_ms=1,
            )

        @staticmethod
        def load_same_run_checkpoint(
            run_id: str, thread_id: str
        ) -> GraphCheckpointEnvelopeV1:
            assert (run_id, thread_id) == ("run-1", "thread-1")
            return GraphCheckpointEnvelopeV1(
                schema_version=1,
                checkpoint_id="checkpoint-1",
                checkpoint_generation=3,
                run_id=run_id,
                langgraph_thread_id=thread_id,
                graph_profile="SIX_ROLE_BASELINE",
                graph_version="resume-contract-v1",
                owner_scope="REQUEST_UNDERSTANDING",
                registered_resume_target=target,
                applied_handoff_id="handoff-1",
                execution_admission_id=None,
                active_handoff_id=None,
                active_handoff_run_sequence=None,
                retrieval_cache_requirements=(),
                created_at_ms=1,
                checkpoint_blob=b"checkpoint",
            )

    class _Registry:
        @staticmethod
        def validate(candidate: AgentNodeResumeTargetV2) -> None:
            assert candidate == target

    runtime = cast(ResumeCheckpointMixin, object.__new__(ResumeCheckpointMixin))
    runtime._graph = _Graph()
    runtime._checkpoint_port = _CheckpointPort()  # type: ignore[assignment]
    runtime._resume_target_registry = _Registry()  # type: ignore[assignment]
    runtime._config_for_thread = lambda workflow_key: {  # type: ignore[method-assign]
        "configurable": {"thread_id": workflow_key}
    }

    pending = runtime.resolve_pending_confirmation("run-1")

    assert pending == {
        "interrupt_id": "interrupt-1",
        "semantic_owner_id": "REQUEST_UNDERSTANDING",
        "resume_target": interrupt["resume_target"],
        "pre_confirmation_status": "ANALYZING",
        "question": "Please clarify recipient",
        "options": [],
        "checkpoint_id": "checkpoint-1",
        "checkpoint_generation": 3,
        "policy_confirmation": None,
    }
