"""Concrete Stage 17 workflow runtime assembled on LangGraph."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Any, cast

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.profiles import (
    GraphProfile,
    PromptArtifactGapError,
)
from google_work_agent.application import (
    BlockRunCommand,
    BlockRunService,
    ClaimReadActionCommand,
    ClaimReadActionService,
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunService,
    CompleteReadActionCommand,
    CompleteReadActionService,
    CompleteWriteRunCommand,
    CompleteWriteRunService,
    ExecuteReadActionService,
    FailReadActionCommand,
    FailReadActionService,
    FailRunCommand,
    FailRunService,
    FinalizeReadActionCommand,
    FinalizeReadActionService,
    MarkWriteActionFailedCommand,
    MarkWriteActionFailedService,
    MarkWriteActionUnknownResultCommand,
    MarkWriteActionUnknownResultService,
    PublishReadOnlyPlanCommand,
    PublishReadOnlyPlanService,
    PublishWritePlanCommand,
    PublishWritePlanService,
    ReadActionDraft,
    ReadEvidenceDraft,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownCreateActionService,
    RecoverUnknownUpdateActionCommand,
    RecoverUnknownUpdateActionService,
    RequireWriteReauthCommand,
    RequireWriteReauthService,
    SaveReadOnlyPlanCommand,
    SaveReadOnlyPlanService,
    SaveWritePlanCommand,
    SaveWritePlanService,
    StoreWriteActionSuccessCommand,
    StoreWriteActionSuccessService,
    VerifyWriteActionCommand,
    VerifyWriteActionService,
    WriteActionDraft,
    WriteEvidenceDraft,
    derive_finalize_intent,
)
from google_work_agent.application.workflows import (
    AgentLocalStateV1,
    ApiDiscoveryAcquisitionAgent,
    ContextRetrievalAgent,
    DomainValidationResult,
    DomainValidationService,
    MultiAgentGraphState,
    PlanReviewAgent,
    RequestUnderstandingAgent,
    ReviewResult,
    SolutionPlanningAgent,
    SupervisorTarget,
    WorkAnalysisAgent,
    WorkflowPhase,
    route_supervisor,
    validate_acquisition_result_v1,
)
from google_work_agent.application.write_actions import (
    ClaimWriteActionCommand,
    ClaimWriteActionService,
    ExecuteWriteActionService,
)
from google_work_agent.domain import ActionStatus, ResultCode, RunStatus
from google_work_agent.ports import (
    EvidenceOriginType,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    UnitOfWork,
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowRuntime,
    WorkflowStartRequest,
)
from google_work_agent.ports.repositories import ActionRecord

JsonObject = dict[str, object]
GraphState = dict[str, object]
REQUEST_AGENT_LOCAL_KEY = "__request_agent_local__"
ACQUISITION_AGENT_LOCAL_KEY = "__acquisition_agent_local__"
ACQUISITION_PLANNING_OUTPUT_KEY = "__acquisition_planning_output__"


class LangGraphWorkflowRuntime(WorkflowRuntime):
    """LangGraph runtime with selectable Stage 18 graph profiles."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        llm_runtime: Any,
        gateway: GoogleWorkspaceGateway,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        signing_secret: str,
        service_instance_id: str,
        checkpoint_database_path: Path,
        graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
        prompt_manifest_path: Path | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._checkpoint_database_path = checkpoint_database_path
        self._graph_profile = graph_profile
        self._checkpoint_database_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(
            self._checkpoint_database_path,
            check_same_thread=False,
        )
        self._checkpointer = SqliteSaver(self._checkpoint_connection)

        self._request_understanding = RequestUnderstandingAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._acquisition = ApiDiscoveryAcquisitionAgent(
            llm_runtime=llm_runtime,
            gateway=gateway,
            manifest_path=prompt_manifest_path,
        )
        self._context = ContextRetrievalAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._analysis = WorkAnalysisAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._planning = SolutionPlanningAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._review = PlanReviewAgent(
            llm_runtime=llm_runtime,
            manifest_path=prompt_manifest_path,
        )
        self._domain_validation = DomainValidationService()

        self._complete_answer_only = CompleteAnswerOnlyRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            message_id_factory=id_factory,
        )
        self._complete_write_run = CompleteWriteRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._block_run = BlockRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._fail_run = FailRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._save_write_plan = SaveWritePlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._save_read_plan = SaveReadOnlyPlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._publish_read_plan = PublishReadOnlyPlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_read = ClaimReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._execute_read = ExecuteReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=gateway,
        )
        self._complete_read = CompleteReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._finalize_read = FinalizeReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._fail_read = FailReadActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._publish_write_plan = PublishWritePlanService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._claim_write = ClaimWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            signing_secret=signing_secret,
            service_instance_id=service_instance_id,
        )
        self._execute_write = ExecuteWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            gateway=gateway,
            now_ms=now_ms,
            signing_secret=signing_secret,
            service_instance_id=service_instance_id,
        )
        self._store_write_success = StoreWriteActionSuccessService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_failed = MarkWriteActionFailedService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._mark_write_unknown = MarkWriteActionUnknownResultService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._verify_write = VerifyWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._require_write_reauth = RequireWriteReauthService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        )
        self._recover_unknown_create = RecoverUnknownCreateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._recover_unknown_update = RecoverUnknownUpdateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )
        self._request_subgraph = self._build_request_subgraph()
        self._acquisition_subgraph = self._build_acquisition_subgraph()
        self._topology = self._topology_for_profile()
        self._graph = self._build_graph()

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        config = self._config_for_thread(request.workflow_key)
        self._graph.invoke(self._initial_state(request), config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self._is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        self._graph.invoke(Command(resume=request.resume_payload), config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": "cancel_requested", "reason_code": request.reason_code},
        )

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        if not self._is_profile_compatible(cast(GraphState, snapshot.values)):
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                payload={"graph_profile": self._graph_profile.value},
            )
        values = cast(GraphState, snapshot.values)
        state = self._recovery_node(values)
        return self._workflow_result_from_state(
            state=state,
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def close(self) -> None:
        self._checkpoint_connection.close()

    def _build_graph(self) -> Any:
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            raise PromptArtifactGapError(
                "PROMPT_ARTIFACT_GAP: SINGLE_BASELINE requires a unified prompt artifact"
            )
        graph = StateGraph(dict)
        for name in self._topology:
            graph.add_node(name, self._node_handler(name))
        graph.add_node("waiting_confirmation", self._waiting_confirmation_node)
        graph.add_node("waiting_approval", self._waiting_approval_node)
        graph.add_node("action_execution", self._action_execution_node)
        graph.add_node("recovery", self._recovery_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, self._topology[0])
        for name in (
            *self._topology,
            "waiting_confirmation",
            "waiting_approval",
            "action_execution",
            "recovery",
            "finalize",
        ):
            graph.add_conditional_edges(name, self._route_next_node, self._edge_map())
        return graph.compile(checkpointer=self._checkpointer)

    def _edge_map(self) -> dict[str, str]:
        edges = {
            "waiting_confirmation": "waiting_confirmation",
            "waiting_approval": "waiting_approval",
            "action_execution": "action_execution",
            "recovery": "recovery",
            "finalize": "finalize",
            "end": END,
        }
        for name in self._topology:
            edges[name] = name
        return edges

    def _initial_state(self, request: WorkflowStartRequest) -> GraphState:
        return {
            "schema_version": 1,
            "run_id": request.run_id,
            "conversation_id": request.conversation_id,
            "thread_id": request.workflow_key,
            "workflow_phase": WorkflowPhase.INITIALIZE.value,
            "request_intent": None,
            "source_fetch_plans": [],
            "acquisition_result": None,
            "context_result": None,
            "analysis_result": None,
            "answer_draft": None,
            "plan_draft": None,
            "plan_review": None,
            "approved_plan_id": None,
            "execution_summary": None,
            "verification_summary": None,
            "finalize_intent": None,
            "user_interrupt": None,
            "retry_budget": {
                "schema_version": 1,
                "profile": "NORMAL",
                "llm_calls_used": 0,
                "additional_acquisitions_used": 0,
                "planning_revisions_used": 0,
                "last_rechecked_planning_revision": 0,
                "semantic_revision_signatures_used": [],
            },
            "prompt_context": {"graph_profile": self._graph_profile.value},
            "trace_context": {
                "agent_invocation_count": 0,
                "llm_call_count": 0,
                "agent_node_log": [],
                "prompt_refs": [],
            },
            "__request__": request,
            "__target__": self._topology[0],
            "__logical_target__": self._topology[0],
        }

    def describe_topology(self) -> tuple[str, ...]:
        return self._topology

    def graph_profile(self) -> GraphProfile:
        return self._graph_profile

    def _topology_for_profile(self) -> tuple[str, ...]:
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            return (
                "request_understanding",
                "acquisition",
                "context_retrieval",
                "work_analysis",
                "solution_planning",
                "plan_review",
                "domain_validation",
            )
        if self._graph_profile is GraphProfile.THREE_STAGE:
            return (
                "stage_one",
                "stage_two",
                "stage_three",
            )
        if self._graph_profile is GraphProfile.SINGLE_BASELINE:
            return ("single_workflow",)
        raise ValueError(f"unsupported graph profile: {self._graph_profile}")

    def _node_handler(self, name: str) -> Any:
        mapping = {
            "request_understanding": self._request_subgraph,
            "acquisition": self._acquisition_subgraph,
            "source_planning": self._source_planning_node,
            "api_acquisition": self._api_acquisition_node,
            "context_retrieval": self._context_retrieval_node,
            "work_analysis": self._work_analysis_node,
            "solution_planning": self._solution_planning_node,
            "plan_review": self._plan_review_node,
            "domain_validation": self._domain_validation_node,
            "stage_one": self._stage_one_node,
            "stage_two": self._stage_two_node,
            "stage_three": self._stage_three_node,
        }
        return mapping[name]

    def _build_request_subgraph(self) -> Any:
        graph = StateGraph(dict)
        graph.add_node("init", self._request_subgraph_init_node)
        graph.add_node("classify", self._request_subgraph_classify_node)
        graph.add_node("finalize", self._request_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "classify")
        graph.add_edge("classify", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="request_understanding_subgraph")

    def _build_acquisition_subgraph(self) -> Any:
        graph = StateGraph(dict)
        graph.add_node("init", self._acquisition_subgraph_init_node)
        graph.add_node("plan_sources", self._acquisition_subgraph_plan_sources_node)
        graph.add_node("plan_validate", self._acquisition_subgraph_plan_validate_node)
        graph.add_node("deterministic_read", self._acquisition_subgraph_read_node)
        graph.add_node("result_validate", self._acquisition_subgraph_result_validate_node)
        graph.add_node("finalize", self._acquisition_subgraph_finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "plan_sources")
        graph.add_edge("plan_sources", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_acquisition_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="acquisition_subgraph")

    def _request_subgraph_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="request_understanding",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_text": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            prompt_ref=self._request_understanding.prompt_ref,
        )
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=invocation_id,
                subgraph_namespace="request_understanding",
                node_name="init",
                prompt_ref=self._request_understanding.prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _request_subgraph_classify_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding.invoke_classify_llm(request)
        output = self._request_understanding.build_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "CLASSIFY_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="request_understanding",
                agent_role="request_understanding",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="request_understanding",
                node_name="classify",
                llm_call_id=f"{request.run_id}:request_understanding.classify",
                prompt_ref=self._request_understanding.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }

    def _request_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[REQUEST_AGENT_LOCAL_KEY])
        request = self._request_from_state(state)
        output = cast(dict[str, object], local_state["typed_result"])
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, output["result"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="request_understanding",
                    agent_role="request_understanding",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="request_understanding",
                    node_name="finalize",
                ),
                REQUEST_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            },
            self._request_understanding.build_state_update(output, request=request),
            decision,
        )
        merged.pop(REQUEST_AGENT_LOCAL_KEY, None)
        return merged

    def _acquisition_subgraph_init_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        additional = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if isinstance(context_result, dict):
            additional = context_result.get("additional_acquisition_request")
        if additional is None and isinstance(analysis_result, dict):
            additional = analysis_result.get("additional_acquisition_request")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="api_discovery_acquisition",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={
                "request_intent": cast(dict[str, object], state["request_intent"]),
                "additional_acquisition_request": cast(dict[str, object] | None, additional),
                "entry_mode": request.entry_mode,
            },
            prompt_ref=self._acquisition.prompt_ref,
        )
        next_state = {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=invocation_id,
                subgraph_namespace="acquisition",
                node_name="init",
                prompt_ref=self._acquisition.prompt_ref,
                agent_invocation_increment=1,
            ),
        }
        if additional is not None:
            next_state[ACQUISITION_PLANNING_OUTPUT_KEY] = cast(dict[str, object], additional)
        return next_state

    def _acquisition_subgraph_plan_sources_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        additional = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if isinstance(context_result, dict):
            additional = context_result.get("additional_acquisition_request")
        if additional is None and isinstance(analysis_result, dict):
            additional = analysis_result.get("additional_acquisition_request")
        llm_result = self._acquisition.invoke_plan_sources_llm(
            request_intent=cast(dict[str, object], state["request_intent"]),
            request=request,
            additional_acquisition_request=cast(dict[str, object] | None, additional),
        )
        output = self._acquisition.build_planning_output_from_llm_result(llm_result)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            ACQUISITION_PLANNING_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_sources",
                llm_call_id=f"{request.run_id}:acquisition.plan_sources",
                prompt_ref=self._acquisition.prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
            ),
        }

    def _acquisition_subgraph_plan_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = cast(dict[str, object], state[ACQUISITION_PLANNING_OUTPUT_KEY])
        source_fetch_plans = planning_output.get("source_fetch_plans")
        if not isinstance(source_fetch_plans, list):
            raise TypeError("acquisition planning output is missing source_fetch_plans")
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = planning_output
        return {
            **state,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="plan_validate",
            ),
        }

    def _route_acquisition_plan_validate(self, state: GraphState) -> str:
        planning_output = cast(dict[str, object], state[ACQUISITION_PLANNING_OUTPUT_KEY])
        return "deterministic_read" if planning_output["result"] == "PLAN_READY" else "finalize"

    def _acquisition_subgraph_read_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = cast(dict[str, object], state[ACQUISITION_PLANNING_OUTPUT_KEY])
        result = self._acquisition.acquire(
            plans=cast(list[dict[str, object]], planning_output["source_fetch_plans"]),
            request=request,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="deterministic_read",
            ),
        }

    def _acquisition_subgraph_result_validate_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        acquisition_result = validate_acquisition_result_v1(state["acquisition_result"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], acquisition_result)
        return {
            **state,
            "acquisition_result": acquisition_result,
            ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="result_validate",
            ),
        }

    def _acquisition_subgraph_finalize_node(self, state: GraphState) -> GraphState:
        local_state = cast(AgentLocalStateV1, state[ACQUISITION_AGENT_LOCAL_KEY])
        planning_output = cast(dict[str, object], state[ACQUISITION_PLANNING_OUTPUT_KEY])
        current = {
            **state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="acquisition",
                agent_role="api_discovery_acquisition",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="acquisition",
                node_name="finalize",
            ),
        }
        if planning_output["result"] != "PLAN_READY":
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=planning_output,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, planning_output["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                self._acquisition.build_planning_state_update(planning_output),
                decision,
            )
        else:
            acquisition_result = cast(dict[str, object], state["acquisition_result"])
            decision = route_supervisor(
                phase=WorkflowPhase.API_ACQUISITION,
                state=cast(MultiAgentGraphState, current),
                result=acquisition_result,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, acquisition_result["status"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, ACQUISITION_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    **self._acquisition.build_planning_state_update(planning_output),
                    **self._acquisition.build_acquisition_state_update(acquisition_result),
                },
                decision,
            )
        merged.pop(ACQUISITION_AGENT_LOCAL_KEY, None)
        merged.pop(ACQUISITION_PLANNING_OUTPUT_KEY, None)
        return merged

    def _request_understanding_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        output = self._request_understanding.classify(request)
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        return self._merge_decision(
            state,
            self._request_understanding.build_state_update(output, request=request),
            decision,
        )

    def _stage_one_node(self, state: GraphState) -> GraphState:
        next_state = self._request_understanding_node(state)
        if next_state.get("__logical_target__") != "source_planning":
            return next_state
        return self._source_planning_node(next_state)

    def _source_planning_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        additional = None
        context_result = state.get("context_result")
        analysis_result = state.get("analysis_result")
        if isinstance(context_result, dict):
            additional = context_result.get("additional_acquisition_request")
        if additional is None and isinstance(analysis_result, dict):
            additional = analysis_result.get("additional_acquisition_request")
        output = self._acquisition.plan_sources(
            request_intent=cast(dict[str, object], state["request_intent"]),
            request=request,
            additional_acquisition_request=cast(dict[str, object] | None, additional),
        )
        decision = route_supervisor(
            phase=WorkflowPhase.SOURCE_PLANNING,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        return self._merge_decision(
            state, self._acquisition.build_planning_state_update(output), decision
        )

    def _api_acquisition_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        result = self._acquisition.acquire(
            plans=cast(list[dict[str, object]], state["source_fetch_plans"]),
            request=request,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.API_ACQUISITION,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(
            state, self._acquisition.build_acquisition_state_update(result), decision
        )

    def _stage_two_node(self, state: GraphState) -> GraphState:
        next_state = self._api_acquisition_node(state)
        if next_state.get("__logical_target__") != "context_retrieval":
            return next_state
        next_state = self._context_retrieval_node(next_state)
        if next_state.get("__logical_target__") != "work_analysis":
            return next_state
        next_state = self._work_analysis_node(next_state)
        if next_state.get("__logical_target__") != "solution_planning":
            return next_state
        return self._solution_planning_node(next_state)

    def _context_retrieval_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        result = self._context.retrieve(
            request_intent=cast(dict[str, object], state["request_intent"]),
            acquisition_result=cast(dict[str, object], state["acquisition_result"]),
            request=request,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._context.build_state_update(result), decision)

    def _work_analysis_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        result = self._analysis.analyze(
            request_intent=cast(dict[str, object], state["request_intent"]),
            context_result=cast(dict[str, object], state["context_result"]),
            request=request,
        )
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._analysis.build_state_update(result), decision)

    def _solution_planning_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        review = cast(dict[str, object] | None, state.get("plan_review"))
        if review is not None and review.get("status") == ReviewResult.REVISE.value:
            if state.get("answer_draft") is not None:
                result = self._planning.revise_answer(
                    request_intent=cast(dict[str, object], state["request_intent"]),
                    answer_draft=cast(dict[str, object], state["answer_draft"]),
                    review_issues=cast(list[dict[str, object]], review["issues"]),
                    review_summary=cast(str | None, review.get("summary")),
                    context_result=cast(dict[str, object], state["context_result"]),
                    analysis_result=cast(dict[str, object], state["analysis_result"]),
                    request=request,
                )
                state_update = self._planning.build_answer_state_update(result)
            else:
                result = self._planning.revise_plan(
                    request_intent=cast(dict[str, object], state["request_intent"]),
                    plan_draft=cast(dict[str, object], state["plan_draft"]),
                    review_issues=cast(list[dict[str, object]], review["issues"]),
                    review_summary=cast(str | None, review.get("summary")),
                    context_result=cast(dict[str, object], state["context_result"]),
                    analysis_result=cast(dict[str, object], state["analysis_result"]),
                    request=request,
                )
                state_update = self._planning.build_plan_state_update(result)
        else:
            analysis_result = cast(dict[str, object], state["analysis_result"])
            if self._should_draft_plan(request.request_text):
                result = self._planning.draft_plan(
                    request_intent=cast(dict[str, object], state["request_intent"]),
                    context_result=cast(dict[str, object], state["context_result"]),
                    analysis_result=analysis_result,
                    request=request,
                )
                state_update = self._planning.build_plan_state_update(result)
            else:
                result = self._planning.answer_only(
                    request_intent=cast(dict[str, object], state["request_intent"]),
                    context_result=cast(dict[str, object], state["context_result"]),
                    analysis_result=analysis_result,
                    request=request,
                )
                state_update = self._planning.build_answer_state_update(result)
        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, state_update, decision)

    def _plan_review_node(self, state: GraphState) -> GraphState:
        request = self._request_from_state(state)
        review = cast(dict[str, object] | None, state.get("plan_review"))
        if review is not None and review.get("status") == ReviewResult.REVISE.value:
            result = self._review.recheck(
                request_intent=cast(dict[str, object], state["request_intent"]),
                context_result=cast(dict[str, object], state["context_result"]),
                analysis_result=cast(dict[str, object], state["analysis_result"]),
                answer_draft=cast(dict[str, object] | None, state.get("answer_draft")),
                plan_draft=cast(dict[str, object] | None, state.get("plan_draft")),
                request=request,
            )
        else:
            result = self._review.inspect(
                request_intent=cast(dict[str, object], state["request_intent"]),
                context_result=cast(dict[str, object], state["context_result"]),
                analysis_result=cast(dict[str, object], state["analysis_result"]),
                answer_draft=cast(dict[str, object] | None, state.get("answer_draft")),
                plan_draft=cast(dict[str, object] | None, state.get("plan_draft")),
                request=request,
            )
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        return self._merge_decision(state, self._review.build_state_update(result), decision)

    def _stage_three_node(self, state: GraphState) -> GraphState:
        next_state = self._plan_review_node(state)
        if next_state.get("__logical_target__") != "domain_validation":
            return next_state
        return self._domain_validation_node(next_state)

    def _domain_validation_node(self, state: GraphState) -> GraphState:
        plan_draft = cast(dict[str, object], state["plan_draft"])
        result = self._domain_validation(
            plan_draft=plan_draft,
            analysis_result=cast(dict[str, object], state["analysis_result"]),
        )
        decision = route_supervisor(
            phase=WorkflowPhase.DOMAIN_VALIDATION,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        if result["result"] == DomainValidationResult.REQUIRE_APPROVAL.value:
            plan_id = self._persist_write_plan(state, plan_draft)
            decision["target"] = SupervisorTarget.WAITING_APPROVAL.value
            decision["state_update"] = {
                **cast(dict[str, object], decision["state_update"]),
                "approved_plan_id": plan_id,
            }
        elif result["result"] == DomainValidationResult.ALLOW_READ.value:
            plan_id = self._persist_read_plan(state, plan_draft)
            decision["target"] = SupervisorTarget.ACTION_EXECUTION.value
            decision["state_update"] = {
                **cast(dict[str, object], decision["state_update"]),
                "approved_plan_id": plan_id,
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        return self._merge_decision(
            state, {"workflow_phase": WorkflowPhase.DOMAIN_VALIDATION.value}, decision
        )

    def _waiting_confirmation_node(self, state: GraphState) -> GraphState:
        interrupt_payload = cast(dict[str, object], state["user_interrupt"])
        request = self._request_from_state(state)
        if (
            RunStatus(self._current_run_status(request.run_id))
            is not RunStatus.WAITING_CONFIRMATION
        ):
            self._transition_run(request.run_id, "request_confirmation")
        resume_payload = interrupt(
            {
                "interrupt_kind": "CONFIRMATION",
                "run_id": request.run_id,
                **interrupt_payload,
            }
        )
        augmented_request = self._request_with_confirmation(
            request,
            cast(dict[str, object], resume_payload),
        )
        return {
            **state,
            "__request__": augmented_request,
            "__target__": self._confirmation_resume_target(interrupt_payload),
            "user_interrupt": None,
            "workflow_phase": WorkflowPhase.SOURCE_PLANNING.value,
            "prompt_context": {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_response": cast(dict[str, object], resume_payload),
            },
        }

    def _waiting_approval_node(self, state: GraphState) -> GraphState:
        plan_id = cast(str | None, state.get("approved_plan_id"))
        payload = {
            "interrupt_kind": "APPROVAL",
            "run_id": state["run_id"],
            "plan_id": plan_id,
        }
        _ = interrupt(payload)
        return {
            **state,
            "__target__": "action_execution",
            "workflow_phase": WorkflowPhase.PREFLIGHT.value,
        }

    def _action_execution_node(self, state: GraphState) -> GraphState:
        plan_id = self._required_string(state.get("approved_plan_id"), "approved_plan_id")
        actions = self._list_actions(plan_id)
        if actions and all(action.effect_type == "READ" for action in actions):
            return self._execute_read_only_plan(state, plan_id, actions)

        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.runs.set_verifying(cast(str, state["run_id"]))
            unit_of_work.commit()
        verification_statuses: list[str] = []
        for action in actions:
            if action.status in {
                ActionStatus.VERIFIED.value,
                ActionStatus.MISMATCH.value,
                ActionStatus.FAILED.value,
                ActionStatus.BLOCKED.value,
                ActionStatus.DEPENDENCY_BLOCKED.value,
            }:
                verification_statuses.append(action.status)
                continue
            if action.status != ActionStatus.APPROVED.value:
                continue
            claim_response = self._claim_write(
                ClaimWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "claim", "action_id": action.id}),
                    action_id=action.id,
                    expected_version=action.version,
                    source_snapshot={},
                    attempt_id=self._id_factory(),
                    nonce=self._id_factory(),
                )
            )
            if (
                not claim_response.applied
                or claim_response.claim_token is None
                or claim_response.attempt_id is None
            ):
                continue
            try:
                executed = self._execute_write(
                    action_id=action.id,
                    claim_token=claim_response.claim_token,
                )
            except GoogleWorkspaceGatewayError as error:
                if error.code in {
                    GoogleWorkspaceErrorCode.AUTH_EXPIRED,
                    GoogleWorkspaceErrorCode.PERMISSION_DENIED,
                }:
                    self._require_write_reauth(
                        RequireWriteReauthCommand(
                            command_id=self._id_factory(),
                            request_hash=self._request_hash(
                                {"kind": "reauth", "action_id": action.id}
                            ),
                            run_id=cast(str, state["run_id"]),
                            action_id=action.id,
                            safe_error_code=error.code.value,
                        )
                    )
                    return {
                        **state,
                        "__target__": "end",
                        "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                        "execution_summary": {"result": "REAUTH_REQUIRED", "action_id": action.id},
                    }
                if error.delivered or error.mutated:
                    unknown = self._mark_write_unknown(
                        MarkWriteActionUnknownResultCommand(
                            command_id=self._id_factory(),
                            request_hash=self._request_hash(
                                {"kind": "unknown", "action_id": action.id}
                            ),
                            action_id=action.id,
                            attempt_id=self._required_string(
                                claim_response.attempt_id, "attempt_id"
                            ),
                            expected_action_version=claim_response.action_version,
                            expected_attempt_version=0,
                            error_code=error.code.value,
                            error_detail=str(error),
                        )
                    )
                    return {
                        **state,
                        "__target__": "recovery",
                        "workflow_phase": WorkflowPhase.RECOVERY.value,
                        "execution_summary": {
                            "result": unknown.result_code,
                            "action_id": action.id,
                            "safe_error_code": error.code.value,
                        },
                    }
                self._mark_write_failed(
                    MarkWriteActionFailedCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash({"kind": "failed", "action_id": action.id}),
                        action_id=action.id,
                        attempt_id=self._required_string(claim_response.attempt_id, "attempt_id"),
                        expected_action_version=claim_response.action_version,
                        expected_attempt_version=0,
                        error_code=error.code.value,
                        error_detail=str(error),
                    )
                )
                verification_statuses.append(ActionStatus.FAILED.value)
                continue

            stored = self._store_write_success(
                StoreWriteActionSuccessCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "store_success", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=self._required_string(claim_response.attempt_id, "attempt_id"),
                    expected_action_version=claim_response.action_version,
                    expected_attempt_version=0,
                    snapshot=executed.snapshot,
                )
            )
            verified = self._verify_write(
                VerifyWriteActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "verify", "action_id": action.id}),
                    action_id=action.id,
                    attempt_id=self._required_string(stored.attempt_id, "attempt_id"),
                    expected_action_version=stored.action_version,
                    verification_id=self._id_factory(),
                )
            )
            verification_statuses.append(verified.action_status)
        if (
            actions
            and verification_statuses
            and all(status == ActionStatus.VERIFIED.value for status in verification_statuses)
        ):
            self._complete_write_run(
                CompleteWriteRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "complete_write_run", "run_id": state["run_id"]}
                    ),
                    run_id=cast(str, state["run_id"]),
                    expected_version=self._current_run_version(cast(str, state["run_id"])),
                )
            )
        return {
            **state,
            "__target__": "finalize",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "execution_summary": {"result": "EXECUTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
        }

    def _recovery_node(self, state: GraphState) -> GraphState:
        unknown_action = self._latest_unknown_action(cast(str, state["run_id"]))
        if unknown_action is None:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
            }
        action, attempt_id = unknown_action
        if action.effect_type == "CREATE":
            response = self._recover_unknown_create(
                RecoverUnknownCreateActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_create", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=0,
                )
            )
        else:
            response = self._recover_unknown_update(
                RecoverUnknownUpdateActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "recover_update", "action_id": action.id}
                    ),
                    action_id=action.id,
                    attempt_id=attempt_id,
                    expected_action_version=action.version,
                    expected_attempt_version=0,
                )
            )
        outcome = (
            "RECOVERY_REQUIRED"
            if response.result_code == ResultCode.RECOVERY_REQUIRED.value
            else "RECOVERED"
        )
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": outcome, "action_id": action.id},
        }

    def _finalize_node(self, state: GraphState) -> GraphState:
        finalize_intent = derive_finalize_intent(state=cast(MultiAgentGraphState, state))
        if finalize_intent is None:
            return {**state, "__target__": "end", "workflow_phase": WorkflowPhase.FINALIZE.value}
        run_id = cast(str, state["run_id"])
        if finalize_intent["intent"] == "COMPLETED" and state.get("answer_draft") is not None:
            draft = cast(dict[str, object], state["answer_draft"])
            self._complete_answer_only(
                CompleteAnswerOnlyRunCommand(
                    command_id=self._id_factory(),
                    conversation_id=cast(str, state["conversation_id"]),
                    run_id=run_id,
                    assistant_message=self._required_string(draft.get("answer"), "answer"),
                    expected_version=self._current_run_version(run_id),
                    request_hash=self._request_hash({"kind": "answer_only", "run_id": run_id}),
                )
            )
        elif finalize_intent["intent"] == "BLOCKED":
            self._block_run(
                BlockRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "block", "run_id": run_id}),
                    run_id=run_id,
                    expected_version=self._current_run_version(run_id),
                    reason_code=finalize_intent["reason_code"],
                )
            )
        elif finalize_intent["intent"] == "FAILED":
            self._fail_run(
                FailRunCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "fail", "run_id": run_id}),
                    run_id=run_id,
                    expected_version=self._current_run_version(run_id),
                    reason_code=finalize_intent["reason_code"],
                )
            )
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.FINALIZE.value,
            "finalize_intent": finalize_intent,
        }

    def _route_next_node(self, state: GraphState) -> str:
        return cast(str, state.get("__target__", "end"))

    def _merge_decision(
        self,
        state: GraphState,
        update: dict[str, object],
        decision: dict[str, object],
    ) -> GraphState:
        decision_state = cast(dict[str, object], decision["state_update"])
        merged = {**state, **update, **decision_state}
        merged["prompt_context"] = {
            **cast(dict[str, object], state.get("prompt_context", {})),
            **cast(dict[str, object], update.get("prompt_context", {})),
            **cast(dict[str, object], decision_state.get("prompt_context", {})),
        }
        merged["trace_context"] = {
            **cast(dict[str, object], state.get("trace_context", {})),
            **cast(dict[str, object], update.get("trace_context", {})),
            **cast(dict[str, object], decision_state.get("trace_context", {})),
        }
        logical_target = self._logical_target_name(cast(str, decision["target"]))
        target = self._target_to_node(cast(str, decision["target"]))
        merged["__logical_target__"] = logical_target
        merged["__target__"] = target
        return merged

    def _logical_target_name(self, target: str) -> str:
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE and target in {
            SupervisorTarget.SOURCE_PLANNING.value,
            SupervisorTarget.API_ACQUISITION.value,
        }:
            return "acquisition"
        mapping = {
            SupervisorTarget.SOURCE_PLANNING.value: "source_planning",
            SupervisorTarget.API_ACQUISITION.value: "api_acquisition",
            SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retrieval",
            SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
            SupervisorTarget.SOLUTION_PLANNING.value: "solution_planning",
            SupervisorTarget.PLAN_REVIEW_INSPECT.value: "plan_review",
            SupervisorTarget.PLAN_REVIEW_RECHECK.value: "plan_review",
            SupervisorTarget.PLANNING_REVISE_ANSWER.value: "solution_planning",
            SupervisorTarget.PLANNING_REVISE_PLAN.value: "solution_planning",
            SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
            SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
            SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
            SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
            SupervisorTarget.REAUTH.value: "end",
            SupervisorTarget.RECOVERY.value: "recovery",
            SupervisorTarget.FINALIZE.value: "finalize",
        }
        return mapping.get(target, "end")

    def _target_to_node(self, target: str) -> str:
        if self._graph_profile is GraphProfile.THREE_STAGE:
            three_stage_mapping = {
                SupervisorTarget.SOURCE_PLANNING.value: "stage_one",
                SupervisorTarget.API_ACQUISITION.value: "stage_two",
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "stage_two",
                SupervisorTarget.WORK_ANALYSIS.value: "stage_two",
                SupervisorTarget.SOLUTION_PLANNING.value: "stage_two",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "stage_three",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "stage_three",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "stage_two",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "stage_two",
                SupervisorTarget.DOMAIN_VALIDATION.value: "stage_three",
                SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
                SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
                SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
                SupervisorTarget.REAUTH.value: "end",
                SupervisorTarget.RECOVERY.value: "recovery",
                SupervisorTarget.FINALIZE.value: "finalize",
            }
            return three_stage_mapping.get(target, "end")
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            six_stage_mapping = {
                SupervisorTarget.SOURCE_PLANNING.value: "acquisition",
                SupervisorTarget.API_ACQUISITION.value: "acquisition",
                SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retrieval",
                SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
                SupervisorTarget.SOLUTION_PLANNING.value: "solution_planning",
                SupervisorTarget.PLAN_REVIEW_INSPECT.value: "plan_review",
                SupervisorTarget.PLAN_REVIEW_RECHECK.value: "plan_review",
                SupervisorTarget.PLANNING_REVISE_ANSWER.value: "solution_planning",
                SupervisorTarget.PLANNING_REVISE_PLAN.value: "solution_planning",
                SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
                SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
                SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
                SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
                SupervisorTarget.REAUTH.value: "end",
                SupervisorTarget.RECOVERY.value: "recovery",
                SupervisorTarget.FINALIZE.value: "finalize",
            }
            return six_stage_mapping.get(target, "end")
        mapping = {
            SupervisorTarget.SOURCE_PLANNING.value: "source_planning",
            SupervisorTarget.API_ACQUISITION.value: "api_acquisition",
            SupervisorTarget.CONTEXT_RETRIEVAL.value: "context_retrieval",
            SupervisorTarget.WORK_ANALYSIS.value: "work_analysis",
            SupervisorTarget.SOLUTION_PLANNING.value: "solution_planning",
            SupervisorTarget.PLAN_REVIEW_INSPECT.value: "plan_review",
            SupervisorTarget.PLAN_REVIEW_RECHECK.value: "plan_review",
            SupervisorTarget.PLANNING_REVISE_ANSWER.value: "solution_planning",
            SupervisorTarget.PLANNING_REVISE_PLAN.value: "solution_planning",
            SupervisorTarget.DOMAIN_VALIDATION.value: "domain_validation",
            SupervisorTarget.WAITING_CONFIRMATION.value: "waiting_confirmation",
            SupervisorTarget.WAITING_APPROVAL.value: "waiting_approval",
            SupervisorTarget.ACTION_EXECUTION.value: "action_execution",
            SupervisorTarget.REAUTH.value: "end",
            SupervisorTarget.RECOVERY.value: "recovery",
            SupervisorTarget.FINALIZE.value: "finalize",
        }
        return mapping.get(target, "end")

    def _confirmation_resume_target(self, interrupt_payload: dict[str, object]) -> str:
        origin_target = cast(str | None, interrupt_payload.get("origin_target"))
        if self._graph_profile is GraphProfile.THREE_STAGE and origin_target is not None:
            if origin_target.startswith(("request_understanding.", "acquisition.")):
                return "stage_one"
            if origin_target.startswith(("context.", "analysis.", "planning.")):
                return "stage_two"
            if origin_target.startswith("review."):
                return "stage_three"
        if self._graph_profile is GraphProfile.SIX_ROLE_BASELINE:
            return "acquisition"
        return "source_planning"

    def _request_from_state(self, state: GraphState) -> WorkflowStartRequest:
        request = state.get("__request__")
        if not isinstance(request, WorkflowStartRequest):
            raise TypeError("workflow state is missing WorkflowStartRequest")
        prompt_context = cast(dict[str, object], state.get("prompt_context", {}))
        confirmation_response = prompt_context.get("confirmation_response")
        if not isinstance(confirmation_response, dict):
            return request
        request_text = (
            request.request_text
            + "\n\n[clarification]\n"
            + dumps(
                {
                    "selected_option_ids": cast(
                        list[str], confirmation_response.get("selected_option_ids", [])
                    ),
                    "free_text": cast(str | None, confirmation_response.get("free_text")),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return WorkflowStartRequest(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
            workflow_key=request.workflow_key,
            entry_mode=request.entry_mode,
            requested_mode=request.requested_mode,
            request_text=request_text,
            selected_resource_ids=request.selected_resource_ids,
            correlation=request.correlation,
            selected_resources=request.selected_resources,
        )

    def _config_for_thread(self, workflow_key: str) -> dict[str, object]:
        return {"configurable": {"thread_id": workflow_key}}

    def _workflow_result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        return self._result_from_state(state=state, workflow_key=workflow_key, run_id=run_id)

    def _result_from_thread(self, *, workflow_key: str, run_id: str) -> WorkflowInvocationResult:
        snapshot = self._graph.get_state(self._config_for_thread(workflow_key))
        return self._result_from_state(
            state=cast(GraphState, snapshot.values),
            workflow_key=workflow_key,
            run_id=run_id,
        )

    def _result_from_state(
        self,
        *,
        state: GraphState,
        workflow_key: str,
        run_id: str,
    ) -> WorkflowInvocationResult:
        run_status = self._current_run_status(run_id)
        if run_status in {
            RunStatus.COMPLETED.value,
            RunStatus.BLOCKED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }:
            outcome = WorkflowOutcome.COMPLETED
        elif run_status == RunStatus.RECOVERY_REQUIRED.value:
            outcome = WorkflowOutcome.RECOVERY_REQUIRED
        elif run_status == RunStatus.REAUTH_REQUIRED.value:
            outcome = WorkflowOutcome.ACCEPTED
        else:
            outcome = WorkflowOutcome.ACCEPTED
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=outcome,
            payload={
                "phase": state.get("workflow_phase"),
                "finalize_intent": state.get("finalize_intent"),
                "user_interrupt": state.get("user_interrupt"),
                "execution_summary": state.get("execution_summary"),
                "verification_summary": state.get("verification_summary"),
                "run_status": run_status,
                "graph_profile": self._graph_profile.value,
            },
        )

    def _is_profile_compatible(self, state: GraphState) -> bool:
        prompt_context = state.get("prompt_context")
        if not isinstance(prompt_context, dict):
            return True
        persisted_profile = prompt_context.get("graph_profile")
        if not isinstance(persisted_profile, str):
            return True
        return persisted_profile == self._graph_profile.value

    def _persist_write_plan(self, state: GraphState, plan_draft: dict[str, object]) -> str:
        run_id = cast(str, state["run_id"])
        run_version = self._current_run_version(run_id)
        context_result = cast(dict[str, object], state["context_result"])
        evidence_drafts = {
            cast(str, item["evidence_id"]): item
            for item in cast(list[dict[str, object]], context_result["evidence_drafts"])
        }
        mapped_evidence = []
        for evidence_id in cast(list[str], plan_draft["evidence_refs"]):
            item = cast(dict[str, object], evidence_drafts[evidence_id])
            mapped_evidence.append(
                WriteEvidenceDraft(
                    evidence_id=evidence_id,
                    origin_type=EvidenceOriginType.DERIVED,
                    kind=cast(str, item["kind"]),
                    excerpt=cast(str, item["excerpt"]),
                    locator_json=None
                    if item.get("locator") is None
                    else dumps(item["locator"], sort_keys=True),
                )
            )
        mapped_actions = tuple(
            WriteActionDraft(
                action_id=cast(str, action["action_id"]),
                position=int(action["position"]),
                tool_name=cast(str, action["tool_name"]),
                arguments=cast(dict[str, object], action["arguments"]),
                expected=cast(dict[str, object], action["expected"]),
                evidence_ids=tuple(cast(list[str], action["evidence_refs"])),
                target_resource_ref_id=cast(str | None, action.get("target_resource_ref_id")),
            )
            for action in cast(list[dict[str, object]], plan_draft["actions"])
        )
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        save_response = self._save_write_plan(
            SaveWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=1,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=mapped_actions,
                evidence=tuple(mapped_evidence),
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_write_plan failed: {save_response.result_code}")
        publish_response = self._publish_write_plan(
            PublishWritePlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_write_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_write_plan failed: {publish_response.result_code}")
        return plan_id

    def _persist_read_plan(self, state: GraphState, plan_draft: dict[str, object]) -> str:
        run_id = cast(str, state["run_id"])
        run_version = self._current_run_version(run_id)
        context_result = cast(dict[str, object], state["context_result"])
        evidence_drafts = {
            cast(str, item["evidence_id"]): item
            for item in cast(list[dict[str, object]], context_result["evidence_drafts"])
        }
        mapped_evidence = []
        for evidence_id in cast(list[str], plan_draft["evidence_refs"]):
            item = cast(dict[str, object], evidence_drafts[evidence_id])
            mapped_evidence.append(
                ReadEvidenceDraft(
                    evidence_id=evidence_id,
                    origin_type=EvidenceOriginType.DERIVED,
                    kind=cast(str, item["kind"]),
                    excerpt=cast(str, item["excerpt"]),
                    locator_json=None
                    if item.get("locator") is None
                    else dumps(item["locator"], sort_keys=True),
                )
            )
        mapped_actions = tuple(
            ReadActionDraft(
                action_id=cast(str, action["action_id"]),
                position=int(action["position"]),
                tool_name=cast(str, action["tool_name"]),
                arguments=cast(dict[str, object], action["arguments"]),
                expected=cast(dict[str, object], action["expected"]),
                evidence_ids=tuple(cast(list[str], action["evidence_refs"])),
                depends_on_action_ids=tuple(
                    cast(list[str], action.get("depends_on_action_ids", []))
                ),
                target_resource_ref_id=cast(str | None, action.get("target_resource_ref_id")),
            )
            for action in cast(list[dict[str, object]], plan_draft["actions"])
        )
        plan_id = self._required_string(plan_draft.get("plan_id"), "plan_id")
        save_response = self._save_read_plan(
            SaveReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "save_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                revision_no=1,
                summary_text=self._required_string(plan_draft.get("summary"), "summary"),
                expected_run_version=run_version,
                actions=mapped_actions,
                evidence=tuple(mapped_evidence),
            )
        )
        if not save_response.applied:
            raise RuntimeError(f"save_read_plan failed: {save_response.result_code}")
        publish_response = self._publish_read_plan(
            PublishReadOnlyPlanCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "publish_read_plan", "plan_id": plan_id}),
                plan_id=plan_id,
                run_id=run_id,
                expected_run_version=save_response.run_version,
            )
        )
        if not publish_response.applied:
            raise RuntimeError(f"publish_read_plan failed: {publish_response.result_code}")
        return plan_id

    def _execute_read_only_plan(
        self,
        state: GraphState,
        plan_id: str,
        actions: tuple[ActionRecord, ...],
    ) -> GraphState:
        verification_statuses: list[str] = []
        for action in actions:
            if action.status in {
                ActionStatus.VERIFIED.value,
                ActionStatus.FAILED.value,
                ActionStatus.BLOCKED.value,
                ActionStatus.DEPENDENCY_BLOCKED.value,
                ActionStatus.REJECTED.value,
                ActionStatus.EXPIRED.value,
                ActionStatus.MISMATCH.value,
            }:
                verification_statuses.append(action.status)
                continue
            if action.status != ActionStatus.PROPOSED.value:
                continue
            claimed = self._claim_read(
                ClaimReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash({"kind": "claim_read", "action_id": action.id}),
                    action_id=action.id,
                    expected_version=action.version,
                )
            )
            if not claimed.applied:
                continue
            try:
                executed = self._execute_read(action_id=action.id)
            except GoogleWorkspaceGatewayError as error:
                failed = self._fail_read(
                    FailReadActionCommand(
                        command_id=self._id_factory(),
                        request_hash=self._request_hash(
                            {"kind": "fail_read", "action_id": action.id}
                        ),
                        action_id=action.id,
                        expected_version=claimed.action_version,
                        safe_error_code=error.code.value,
                        retryable=False,
                        safe_error_detail=str(error),
                    )
                )
                verification_statuses.append(failed.action_status)
                continue
            completed = self._complete_read(
                CompleteReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "complete_read", "action_id": action.id}
                    ),
                    action_id=action.id,
                    expected_version=claimed.action_version,
                    output_json=executed.output_json,
                    resource_refs=executed.resource_refs,
                    evidence=executed.evidence,
                )
            )
            finalized = self._finalize_read(
                FinalizeReadActionCommand(
                    command_id=self._id_factory(),
                    request_hash=self._request_hash(
                        {"kind": "finalize_read", "action_id": action.id}
                    ),
                    action_id=action.id,
                    expected_version=completed.action_version,
                )
            )
            verification_statuses.append(finalized.action_status)
        return {
            **state,
            "__target__": "finalize",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "execution_summary": {"result": "READ_EXECUTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
        }

    def _transition_run(self, run_id: str, transition_name: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            if transition_name == "start_analysis" and run.status is not RunStatus.CREATED:
                return
            if transition_name == "begin_retrieval" and run.status in {
                RunStatus.RETRIEVING,
                RunStatus.PLANNING,
                RunStatus.WAITING_APPROVAL,
            }:
                return
            if transition_name == "begin_planning" and run.status is not RunStatus.RETRIEVING:
                return
            if (
                transition_name == "request_confirmation"
                and run.status is RunStatus.WAITING_CONFIRMATION
            ):
                return
            repository_method = getattr(unit_of_work.runs, transition_name)
            result = repository_method(
                run_id,
                expected_version=run.version,
                finished_at_ms=None,
            )
            if result.applied:
                unit_of_work.commit()

    def _current_run_status(self, run_id: str) -> str:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.status.value

    def _current_run_version(self, run_id: str) -> int:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            return run.version

    def _list_actions(self, plan_id: str) -> tuple[ActionRecord, ...]:
        with self._unit_of_work_factory() as unit_of_work:
            return tuple(
                sorted(unit_of_work.actions.list_by_plan(plan_id), key=lambda item: item.position)
            )

    def _latest_unknown_action(self, run_id: str) -> tuple[ActionRecord, str] | None:
        with self._unit_of_work_factory() as unit_of_work:
            plans = unit_of_work.plans.list_by_run(run_id)
            if not plans:
                return None
            latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
            for action in unit_of_work.actions.list_by_plan(latest_plan.id):
                if action.status != ActionStatus.UNKNOWN_RESULT.value:
                    continue
                approval = unit_of_work.approvals.get_active_by_action(action.id)
                if approval is None:
                    continue
                attempts = unit_of_work.execution_attempts.list_by_approval(approval.id)
                if not attempts:
                    continue
                latest_attempt = sorted(attempts, key=lambda item: item.attempt_no)[-1]
                return action, latest_attempt.id
        return None

    def _request_with_confirmation(
        self,
        request: WorkflowStartRequest,
        resume_payload: dict[str, object],
    ) -> WorkflowStartRequest:
        del resume_payload
        return WorkflowStartRequest(
            run_id=request.run_id,
            conversation_id=request.conversation_id,
            workflow_key=request.workflow_key,
            entry_mode=request.entry_mode,
            requested_mode=request.requested_mode,
            request_text=request.request_text,
            selected_resource_ids=request.selected_resource_ids,
            correlation=request.correlation,
            selected_resources=request.selected_resources,
        )

    def _required_string(self, value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value

    def _request_hash(self, payload: dict[str, object]) -> str:
        return sha256(dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _should_draft_plan(self, request_text: str) -> bool:
        lowered = request_text.lower()
        return any(
            token in lowered
            for token in (
                "create",
                "update",
                "send",
                "delete",
                "read",
                "summarize",
                "show",
                "list",
                "find",
                "get",
                "search",
            )
        )
