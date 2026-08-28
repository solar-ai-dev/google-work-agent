"""THREE_STAGE candidate profile native LangGraph subgraphs.

THREE_STAGE is an E06-A architecture candidate under comparison, not a
feature shipped alongside the default SIX_ROLE_BASELINE profile. Three
subgraphs:

- ``ThreeStageOneSubgraph``: init -> request_source -> plan_validate
  -[PLAN_READY]-> deterministic_read -> result_validate -> finalize
  -[else]-------------------------------------------------^
- ``ThreeStageTwoSubgraph``: init -> reason_plan -> result_validate -> finalize
  (a single fused LLM call produces context+analysis+planning results)
- ``ThreeStageReviewSubgraph``: init -> review -> result_validate -> finalize
  (reuses the same review agent/contract as the SIX_ROLE_BASELINE review subgraph)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    merge_trace_context,
    record_llm_result,
)
from google_work_agent.adapters.langgraph.main.state import (
    PROFILE_AGENT_LOCAL_KEY,
    PROFILE_REASON_PLAN_OUTPUT_KEY,
    PROFILE_REQUEST_SOURCE_OUTPUT_KEY,
    REVIEW_AGENT_LOCAL_KEY,
    REVIEW_MODE_KEY,
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    ProfileReasonPlanLocalState,
    ProfileRequestSourceLocalState,
    ReviewLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.profile_shared import (
    build_no_fetch_acquisition_result,
    build_profile_retrieval_result,
    build_profile_tool_route_plan,
    planning_result_from_projection,
    profile_post_read_prompt_input,
    profile_reason_plan_state_update,
    profile_request_source_prompt_input,
    profile_trace_context,
)
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    build_source_planning_clarification_question,
    validate_acquisition_result_v1,
)
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    ReviewResult,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.plan_review import PlanReviewAgent
from google_work_agent.application.orchestration.profile_fused import (
    PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
    PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
    validate_profile_reason_plan_output_v1,
    validate_profile_request_source_output_v1,
)
from google_work_agent.application.orchestration.request_understanding import (
    RequestUnderstandingAgent,
    build_user_interrupt_v1,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.orchestration.solution_planning import (
    SolutionPlanningAgent,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.orchestration.tool_routing import ToolRouteCoordinator
from google_work_agent.ports.llm import PromptReference

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
RequestSourceConfirmInline = Callable[
    [ProfileRequestSourceLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class ThreeStageOneSubgraph:
    """Builds and executes the ``stage_one`` (request+source+read) subgraph."""

    def __init__(
        self,
        *,
        request_understanding_agent: RequestUnderstandingAgent,
        acquisition_agent: ApiDiscoveryAcquisitionAgent,
        tool_route_coordinator: ToolRouteCoordinator,
        prompt_ref: PromptReference,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: RequestSourceConfirmInline,
    ) -> None:
        self._request_understanding_agent = request_understanding_agent
        self._acquisition_agent = acquisition_agent
        self._tool_route_coordinator = tool_route_coordinator
        self._prompt_ref = prompt_ref
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            ProfileRequestSourceLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("request_source", self._request_source_node)
        graph.add_node("plan_validate", self._plan_validate_node)
        graph.add_node("deterministic_read", self._read_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "request_source")
        graph.add_edge("request_source", "plan_validate")
        graph.add_conditional_edges(
            "plan_validate",
            self._route_plan_validate,
            {
                "deterministic_read": "deterministic_read",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"plan_validate": "plan_validate", "end": END},
        )
        return graph.compile(name="three_stage_one_subgraph")

    @staticmethod
    def _route_after_finalize(state: ProfileRequestSourceLocalState) -> str:
        if state.get("__profile_request_source_confirmation_resolved__"):
            return "plan_validate"
        return "end"

    def _init_node(self, state: ProfileRequestSourceLocalState) -> ProfileRequestSourceLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="request_source_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=profile_request_source_prompt_input(request),
            prompt_ref=self._prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage1",
                node_name="init",
                prompt_ref=self._prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _request_source_node(
        self, state: ProfileRequestSourceLocalState
    ) -> ProfileRequestSourceLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding_agent._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=profile_request_source_prompt_input(request),
            output_schema=PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
            trace_context=profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.three.stage1.initial",
            ),
        )
        output = validate_profile_request_source_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REQUEST_SOURCE_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REQUEST_SOURCE_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="request_source",
                llm_call_id=f"{request.run_id}:profile.three.stage1.initial",
                prompt_ref=self._prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _plan_validate_node(
        self, state: ProfileRequestSourceLocalState
    ) -> ProfileRequestSourceLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        request_intent, tool_route_plan = build_profile_tool_route_plan(
            prompt_output["request_intent"],
            id_factory=self._id_factory,
            coordinator=self._tool_route_coordinator,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = prompt_output
        next_state: ProfileRequestSourceLocalState = {
            **state,
            "request_intent": request_intent,
            "tool_route_plan": tool_route_plan,
            "source_fetch_plans": source_plan["source_fetch_plans"],
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "__profile_request_source_confirmation_resolved__": False,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="plan_validate",
            ),
        }
        if source_plan["result"] == "NO_FETCH_NEEDED":
            next_state["acquisition_result"] = build_no_fetch_acquisition_result()
        if source_plan["result"] == "NEEDS_CONFIRMATION":
            question = build_source_planning_clarification_question(
                output=source_plan,
                request_intent=request_intent,
            )
            interrupt_id = self._id_factory()
            next_state["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            next_state["user_interrupt"] = cast(
                Any,
                {
                    **build_user_interrupt_v1(question),
                    "interrupt_id": interrupt_id,
                },
            )
            next_state["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": {
                    "schema_version": 1,
                    "interrupt_id": interrupt_id,
                    "semantic_owner_id": "RETRIEVAL",
                    "origin_target": question["origin_target"],
                },
            }
        return next_state

    def _route_plan_validate(self, state: ProfileRequestSourceLocalState) -> str:
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        return "deterministic_read" if source_plan["result"] == "PLAN_READY" else "finalize"

    def _read_node(self, state: ProfileRequestSourceLocalState) -> ProfileRequestSourceLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_retrieval")
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        result = self._acquisition_agent.acquire(
            plans=state["source_fetch_plans"],
            request=request,
            request_intent=state.get("request_intent"),
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "READ_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            "acquisition_result": result,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="deterministic_read",
            ),
        }

    def _result_validate_node(
        self, state: ProfileRequestSourceLocalState
    ) -> ProfileRequestSourceLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        acquisition_result = validate_acquisition_result_v1(state["acquisition_result"])
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = cast(dict[str, object], acquisition_result)
        return {
            **state,
            "acquisition_result": acquisition_result,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="result_validate",
            ),
        }

    def _finalize_node(
        self, state: ProfileRequestSourceLocalState
    ) -> ProfileRequestSourceLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        if source_plan["result"] == "NEEDS_CONFIRMATION" and isinstance(
            state.get("user_interrupt"), Mapping
        ):
            _response, early_return_patch = self._confirm_inline(state)
            if early_return_patch is not None:
                return cast(
                    ProfileRequestSourceLocalState,
                    {
                        **state,
                        **early_return_patch,
                        "__profile_request_source_confirmation_resolved__": False,
                    },
                )
            resolved = self._request_source_node(state)
            prompt_context = dict(cast(dict[str, object], resolved.get("prompt_context", {})))
            prompt_context.pop("confirmation_interrupt", None)
            return cast(
                ProfileRequestSourceLocalState,
                {
                    **resolved,
                    "user_interrupt": None,
                    "prompt_context": prompt_context,
                    "__profile_request_source_confirmation_resolved__": True,
                },
            )
        request_intent = _require_state_value(state["request_intent"], "request_intent")
        current: ProfileRequestSourceLocalState = {
            **state,
            "request_intent": request_intent,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_one",
                agent_role="request_source_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage1",
                node_name="finalize",
            ),
        }
        if source_plan["result"] != "PLAN_READY":
            decision = route_supervisor(
                phase=WorkflowPhase.SOURCE_PLANNING,
                state=cast(MultiAgentGraphState, current),
                result=source_plan,
            )
            updated_local = dict(local_state)
            updated_local["node_state"] = "FINALIZED"
            updated_local["disposition"] = {
                "schema_version": 1,
                "status": cast(str, source_plan["result"]),
                "next_target": cast(str, decision["target"]),
                "reason_code": cast(str | None, decision.get("reason_code")),
            }
            merged = self._merge_decision(
                {**current, PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    "request_intent": request_intent,
                    **self._acquisition_agent.build_planning_state_update(source_plan),
                },
                decision,
            )
        else:
            acquisition_result = _require_state_value(
                state["acquisition_result"], "acquisition_result"
            )
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
                {**current, PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local)},
                {
                    "request_intent": request_intent,
                    **self._acquisition_agent.build_planning_state_update(source_plan),
                    **self._acquisition_agent.build_acquisition_state_update(acquisition_result),
                },
                decision,
            )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REQUEST_SOURCE_OUTPUT_KEY, None)
        return cast(ProfileRequestSourceLocalState, merged)


class ThreeStageTwoSubgraph:
    """Builds and executes the ``stage_two`` (fused evidence/analysis/plan) subgraph."""

    def __init__(
        self,
        *,
        request_understanding_agent: RequestUnderstandingAgent,
        planning_agent: SolutionPlanningAgent,
        evidence_store: RunScopedEvidenceStore,
        prompt_ref: PromptReference,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
    ) -> None:
        self._request_understanding_agent = request_understanding_agent
        self._planning_agent = planning_agent
        self._evidence_store = evidence_store
        self._prompt_ref = prompt_ref
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            ProfileReasonPlanLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("reason_plan", self._reason_plan_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "reason_plan")
        graph.add_edge("reason_plan", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="three_stage_two_subgraph")

    def _init_node(self, state: ProfileReasonPlanLocalState) -> ProfileReasonPlanLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="evidence_analysis_plan_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=profile_post_read_prompt_input(state),
            prompt_ref=self._prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage2",
                node_name="init",
                prompt_ref=self._prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _reason_plan_node(self, state: ProfileReasonPlanLocalState) -> ProfileReasonPlanLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._request_understanding_agent._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=profile_post_read_prompt_input(state),
            output_schema=PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
            trace_context=profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.three.stage2.initial",
            ),
        )
        output = validate_profile_reason_plan_output_v1(llm_result.structured_output)
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REASON_PLAN_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], output)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            PROFILE_REASON_PLAN_OUTPUT_KEY: output,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage2",
                node_name="reason_plan",
                llm_call_id=f"{request.run_id}:profile.three.stage2.initial",
                prompt_ref=self._prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _result_validate_node(
        self, state: ProfileReasonPlanLocalState
    ) -> ProfileReasonPlanLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = output
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_two",
                agent_role="evidence_analysis_plan_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage2",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: ProfileReasonPlanLocalState) -> ProfileReasonPlanLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        context_result = output["context_result"]
        analysis_result = output["analysis_result"]
        planning_result = output["planning_result"]
        retrieval_result, evidence_drafts = build_profile_retrieval_result(
            context_result,
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            tool_route_plan=_require_state_value(state["tool_route_plan"], "tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            artifact_id=self._id_factory(),
        )
        self._evidence_store.put(run_id=request.run_id, evidence_drafts=evidence_drafts)
        result = planning_result_from_projection(planning_result)
        state_update = {
            **profile_reason_plan_state_update(output, planning_agent=self._planning_agent),
            "retrieval_result": retrieval_result,
        }
        decision = route_supervisor(
            phase=WorkflowPhase.SOLUTION_PLANNING,
            state=cast(
                MultiAgentGraphState,
                {
                    **state,
                    "context_result": context_result,
                    "analysis_result": analysis_result,
                },
            ),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="stage_two",
                    agent_role="evidence_analysis_plan_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="three.stage2",
                    node_name="finalize",
                ),
            },
            state_update,
            decision,
        )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REASON_PLAN_OUTPUT_KEY, None)
        return cast(ProfileReasonPlanLocalState, merged)


class ThreeStageReviewSubgraph:
    """Builds and executes the ``stage_three`` (review) subgraph."""

    def __init__(
        self,
        *,
        agent: PlanReviewAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision

    def build(self) -> Any:
        graph = StateGraph(
            ReviewLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("review", self._review_node)
        graph.add_node("result_validate", self._result_validate_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "init")
        graph.add_edge("init", "review")
        graph.add_edge("review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile(name="three_stage_review_subgraph")

    def _init_node(self, state: ReviewLocalState) -> ReviewLocalState:
        invocation_id = self._id_factory()
        review = state["plan_review"]
        mode = (
            "recheck"
            if review is not None and review.get("status") == ReviewResult.REVISE.value
            else "inspect"
        )
        prompt_ref = (
            self._agent.recheck_prompt_ref if mode == "recheck" else self._agent.inspect_prompt_ref
        )
        local_state = build_agent_local_state(
            agent_role="review",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection={"mode": mode},
            prompt_ref=prompt_ref,
        )
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: local_state,
            REVIEW_MODE_KEY: mode,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=invocation_id,
                subgraph_namespace="three.stage3",
                node_name="init",
                prompt_ref=prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _review_node(self, state: ReviewLocalState) -> ReviewLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        mode = state[REVIEW_MODE_KEY]
        if mode == "recheck":
            llm_result = self._agent.invoke_recheck_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                allowed_statuses=frozenset({ReviewResult.PASS.value, ReviewResult.BLOCK.value}),
            )
            llm_call_id = f"{request.run_id}:review.recheck"
        else:
            llm_result = self._agent.invoke_inspect_llm(
                request_intent=_require_state_value(state["request_intent"], "request_intent"),
                context_result=_require_state_value(state["context_result"], "context_result"),
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
                request=request,
            )
            result = self._agent.build_output_from_llm_result(
                llm_result,
                analysis_result=_require_state_value(state["analysis_result"], "analysis_result"),
                answer_draft=state["answer_draft"],
                plan_draft=state["plan_draft"],
            )
            llm_call_id = f"{request.run_id}:review.inspect"
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], result)
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "plan_review": result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage3",
                node_name="review",
                llm_call_id=llm_call_id,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _result_validate_node(self, state: ReviewLocalState) -> ReviewLocalState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = result
        return {
            **state,
            REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="stage_three",
                agent_role="review",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="three.stage3",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: ReviewLocalState) -> ReviewLocalState:
        local_state = cast(AgentLocalStateV1, state[REVIEW_AGENT_LOCAL_KEY])
        result = _require_state_value(state["plan_review"], "plan_review")
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "FINALIZED"
        updated_local["disposition"] = {
            "schema_version": 1,
            "status": cast(str, result["status"]),
            "next_target": cast(str, decision["target"]),
            "reason_code": cast(str | None, decision.get("reason_code")),
        }
        merged = self._merge_decision(
            {
                **state,
                REVIEW_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="stage_three",
                    agent_role="review",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="three.stage3",
                    node_name="finalize",
                ),
            },
            self._agent.build_state_update(result),
            decision,
        )
        merged.pop(REVIEW_AGENT_LOCAL_KEY, None)
        merged.pop(REVIEW_MODE_KEY, None)
        return cast(ReviewLocalState, merged)
