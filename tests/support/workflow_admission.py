from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.checkpoint_control import (
    LangGraphCheckpointControlAdapter,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.use_cases.run.coordinator_outcomes import RunOutcomeHandler
from google_work_agent.application.use_cases.run.get_execution_context import (
    GetExecutionContextQuery,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventHandler,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffV1,
)


class _State(TypedDict):
    value: int


def build_test_admission_callbacks(
    *,
    checkpoint_path: Path,
    get_execution_context: Any,
    unit_of_work_factory: Any,
    workflow_runtime: Any,
    event_publisher: Any,
    now_ms: Any,
    checkpoint: SqliteCheckpointAdapter | None = None,
):
    checkpoint = checkpoint or SqliteCheckpointAdapter(checkpoint_path, now_ms=now_ms)
    checkpoint_control = LangGraphCheckpointControlAdapter(
        checkpoint_port=checkpoint,
        native_saver=checkpoint,
    )
    graph_builder = StateGraph(_State)
    graph_builder.add_node("owner", lambda state: {"value": state["value"] + 1})
    graph_builder.add_edge(START, "owner")
    graph_builder.add_edge("owner", END)
    graph = graph_builder.compile(checkpointer=checkpoint)
    outcome_handler = RunOutcomeHandler(
        unit_of_work_factory=unit_of_work_factory,
        project_run_event=ProjectRunEventHandler(event_publisher),
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

    def materialize(admission: WorkflowExecutionAdmissionV1, handoff: WorkflowHandoffV1):
        binding = admission.effective_binding
        if binding.execution_kind == "START":
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
                        config={"configurable": {"thread_id": binding.langgraph_thread_id}},
                        interrupt_before=["owner"],
                    )
        elif admission.submission_kind == "NORMAL_HANDOFF":
            latest = checkpoint.load_same_run_checkpoint(
                binding.run_id, binding.langgraph_thread_id
            )
            assert latest is not None
            resume_target = binding.resume_target
            assert resume_target is not None
            goto_node = (
                workflow_runtime.control_resume_node(resume_target.stage_id)
                if resume_target.kind == "MAIN_CONTROL"
                else workflow_runtime.agent_resume_node(resume_target.semantic_owner_id)
            )
            if handoff.control is None:
                checkpoint_control.materialize_resume_target(latest, goto_node=goto_node)
            else:
                checkpoint_control.materialize_control(
                    latest,
                    handoff.control,
                    goto_node=(
                        None if handoff.control.kind == "CONFIRMATION_RESPONSE" else goto_node
                    ),
                )
        result = checkpoint.load_same_run_checkpoint(
            admission.effective_binding.run_id,
            admission.effective_binding.langgraph_thread_id,
        )
        assert result is not None
        return result

    def request(admission: WorkflowExecutionAdmissionV1) -> WorkflowStartRequest:
        binding = admission.effective_binding
        context = get_execution_context(GetExecutionContextQuery(binding.run_id))
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
        context = get_execution_context(GetExecutionContextQuery(binding.run_id))
        assert context is not None
        latest = checkpoint.load_same_run_checkpoint(binding.run_id, binding.langgraph_thread_id)
        assert latest is not None
        active_target = (
            target(admission) if binding.execution_kind == "START" else binding.resume_target
        )
        assert active_target is not None
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id=admission.handoff_id,
            owner_scope=latest.owner_scope,
            resume_target=active_target,
        ):
            result = (
                workflow_runtime.start(request(admission))
                if binding.execution_kind == "START"
                else workflow_runtime.resume(
                    WorkflowResumeRequest(
                        run_id=context.run_id,
                        workflow_key=context.workflow_key,
                        resume_kind="CONSUMED_CONTINUATION_RECOVERY",
                        resume_payload={},
                        correlation=WorkflowCorrelationContext(
                            request_id=admission.admission_id,
                            command_id=admission.handoff_id,
                            api_contract_version="1",
                        ),
                    )
                )
            )
        current = get_execution_context(GetExecutionContextQuery(binding.run_id))
        outcome_handler.handle_result(
            binding.run_id,
            result.outcome,
            result.payload,
            context.version if current is None else current.version,
        )

    return checkpoint, materialize, invoke
