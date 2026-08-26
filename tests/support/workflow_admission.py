from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.coordinator_outcomes import RunOutcomeHandler
from google_work_agent.ports import WorkflowCorrelationContext, WorkflowStartRequest
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    WorkflowExecutionAdmissionV1,
)


class _State(TypedDict):
    value: int


def build_test_admission_callbacks(
    *,
    checkpoint_path: Path,
    query_service: Any,
    unit_of_work_factory: Any,
    workflow_runtime: Any,
    event_publisher: Any,
    now_ms: Any,
    checkpoint: SqliteCheckpointAdapter | None = None,
):
    checkpoint = checkpoint or SqliteCheckpointAdapter(checkpoint_path, now_ms=now_ms)
    graph_builder = StateGraph(_State)
    graph_builder.add_node("owner", lambda state: {"value": state["value"] + 1})
    graph_builder.add_edge(START, "owner")
    graph_builder.add_edge("owner", END)
    graph = graph_builder.compile(checkpointer=checkpoint)
    outcome_handler = RunOutcomeHandler(
        unit_of_work_factory=unit_of_work_factory,
        event_publisher=event_publisher,
        now_ms=now_ms,
    )

    def target(admission: WorkflowExecutionAdmissionV1) -> AgentNodeResumeTargetV2:
        profile = admission.effective_binding.graph_profile
        return AgentNodeResumeTargetV2(
            "AGENT_NODE",
            "REQUEST_UNDERSTANDING",
            {
                "SINGLE_BASELINE": "UNIFIED_AGENT",
                "THREE_STAGE": "STAGE_REQUEST_ROUTE_RETRIEVAL",
                "SIX_ROLE_BASELINE": "SIX_REQUEST_UNDERSTANDING",
            }[profile],
            "request.identify_goal",
            profile,
            admission.effective_binding.graph_version,
        )

    def materialize(admission: WorkflowExecutionAdmissionV1):
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id=admission.handoff_id,
            owner_scope="REQUEST_UNDERSTANDING",
            resume_target=target(admission),
        ):
            if hasattr(workflow_runtime, "prepare_start"):
                workflow_runtime.prepare_start(request(admission))
            else:
                graph.invoke(
                    {"value": 0},
                    config={
                        "configurable": {
                            "thread_id": admission.effective_binding.langgraph_thread_id
                        }
                    },
                    interrupt_before=["owner"],
                )
        result = checkpoint.load_same_run_checkpoint(
            admission.effective_binding.run_id,
            admission.effective_binding.langgraph_thread_id,
        )
        assert result is not None
        return result

    def request(admission: WorkflowExecutionAdmissionV1) -> WorkflowStartRequest:
        binding = admission.effective_binding
        context = query_service.get_run_execution_context(binding.run_id)
        assert context is not None
        return WorkflowStartRequest(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            workflow_key=context.workflow_key,
            entry_mode=context.entry_mode,
            requested_mode=context.requested_mode,
            request_text=context.request_text,
            selected_resource_ids=context.selected_resource_ids,
            correlation=WorkflowCorrelationContext(
                request_id=admission.admission_id,
                command_id=admission.handoff_id,
                api_contract_version="1",
            ),
            selected_resources=context.selected_resources,
        )

    def invoke(admission: WorkflowExecutionAdmissionV1, _handoff: object) -> None:
        binding = admission.effective_binding
        context = query_service.get_run_execution_context(binding.run_id)
        assert context is not None
        result = workflow_runtime.start(request(admission))
        current = query_service.get_run_execution_context(binding.run_id)
        outcome_handler.handle_result(
            binding.run_id,
            result.outcome,
            result.payload,
            context.version if current is None else current.version,
        )

    return checkpoint, materialize, invoke
