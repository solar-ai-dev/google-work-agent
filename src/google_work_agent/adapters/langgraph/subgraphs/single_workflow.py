"""SINGLE_BASELINE candidate profile native LangGraph subgraph.

SINGLE_BASELINE is an E06-A architecture candidate under comparison, not a
feature shipped alongside the default SIX_ROLE_BASELINE profile.

init -> request_source -> plan_validate -[PLAN_READY]-> deterministic_read
                                         -[NO_FETCH_NEEDED]-> reason_plan
                                         -[else]------------------------> finalize
deterministic_read -> reason_plan -> self_review -> result_validate -> finalize
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
    GraphState,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import SingleWorkflowLocalState
from google_work_agent.adapters.langgraph.subgraphs.profile_shared import (
    build_no_fetch_acquisition_result,
    build_profile_retrieval_result,
    build_profile_tool_route_plan,
    planning_result_from_projection,
    profile_planning_state_update,
    profile_post_read_prompt_input,
    profile_request_source_prompt_input,
    profile_trace_context,
)
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    build_source_planning_clarification_question,
)
from google_work_agent.application.orchestration.confirmation import build_user_interrupt_v1
from google_work_agent.application.orchestration.contracts import (
    AgentLocalStateV1,
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.plan_review import PlanReviewAgent
from google_work_agent.application.orchestration.profile_fused import (
    PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
    PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
    validate_profile_reason_plan_output_v1,
    validate_profile_request_source_output_v1,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.orchestration.solution_planning import (
    SolutionPlanningAgent,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [SingleWorkflowLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class SingleWorkflowSubgraph:
    """Builds and executes the ``single_workflow`` native subgraph."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        acquisition_agent: ApiDiscoveryAcquisitionAgent,
        planning_agent: SolutionPlanningAgent,
        review_agent: PlanReviewAgent,
        tool_catalog: SignedToolRegistry,
        evidence_store: RunScopedEvidenceStore,
        request_source_prompt_ref: PromptReference,
        reason_plan_prompt_ref: PromptReference,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._acquisition_agent = acquisition_agent
        self._planning_agent = planning_agent
        self._review_agent = review_agent
        self._tool_catalog = tool_catalog
        self._evidence_store = evidence_store
        self._request_source_prompt_ref = request_source_prompt_ref
        self._reason_plan_prompt_ref = reason_plan_prompt_ref
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            SingleWorkflowLocalState,
            input_schema=GraphState,
            output_schema=ParentGraphState,
        )
        graph.add_node("init", self._init_node)
        graph.add_node("request_source", self._request_source_node)
        graph.add_node("plan_validate", self._plan_validate_node)
        graph.add_node("deterministic_read", self._read_node)
        graph.add_node("reason_plan", self._reason_plan_node)
        graph.add_node("self_review", self._self_review_node)
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
                "reason_plan": "reason_plan",
                "finalize": "finalize",
            },
        )
        graph.add_edge("deterministic_read", "reason_plan")
        graph.add_edge("reason_plan", "self_review")
        graph.add_edge("self_review", "result_validate")
        graph.add_edge("result_validate", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"plan_validate": "plan_validate", "end": END},
        )
        return graph.compile(name="single_workflow_subgraph")

    @staticmethod
    def _route_after_finalize(state: SingleWorkflowLocalState) -> str:
        if state.get("__profile_request_source_confirmation_resolved__"):
            return "plan_validate"
        return "end"

    def _init_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        local_state = build_agent_local_state(
            agent_role="unified_agent",
            invocation_id=invocation_id,
            node_state="INITIALIZED",
            input_projection=profile_request_source_prompt_input(request),
            prompt_ref=self._request_source_prompt_ref,
        )
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: local_state,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=invocation_id,
                subgraph_namespace="single",
                node_name="init",
                prompt_ref=self._request_source_prompt_ref,
                agent_invocation_increment=1,
            ),
        }

    def _request_source_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._request_source_prompt_ref,
            prompt_input=profile_request_source_prompt_input(request),
            output_schema=PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA,
            trace_context=profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.single.request_source.initial",
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
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="request_source",
                llm_call_id=f"{request.run_id}:profile.single.request_source.initial",
                prompt_ref=self._request_source_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _plan_validate_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        request_intent, tool_route_plan = build_profile_tool_route_plan(
            prompt_output["request_intent"],
            id_factory=self._id_factory,
            tool_catalog=self._tool_catalog,
        )
        updated_local = dict(local_state)
        updated_local["node_state"] = "PLAN_VALIDATED"
        updated_local["typed_result"] = prompt_output
        next_state: SingleWorkflowLocalState = {
            **state,
            "request_intent": request_intent,
            "tool_route_plan": tool_route_plan,
            "source_fetch_plans": source_plan["source_fetch_plans"],
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "__profile_request_source_confirmation_resolved__": False,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
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

    def _route_plan_validate(self, state: SingleWorkflowLocalState) -> str:
        prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
        source_plan = prompt_output["source_plan"]
        if source_plan["result"] == "PLAN_READY":
            return "deterministic_read"
        if source_plan["result"] == "NO_FETCH_NEEDED":
            return "reason_plan"
        return "finalize"

    def _read_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
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
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="deterministic_read",
            ),
        }

    def _reason_plan_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "begin_planning")
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._reason_plan_prompt_ref,
            prompt_input=profile_post_read_prompt_input(state),
            output_schema=PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA,
            trace_context=profile_trace_context(
                request=request,
                llm_call_id=f"{request.run_id}:profile.single.reason_plan.initial",
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
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="reason_plan",
                llm_call_id=f"{request.run_id}:profile.single.reason_plan.initial",
                prompt_ref=self._reason_plan_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _self_review_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        request = request_from_state(state)
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        output = state[PROFILE_REASON_PLAN_OUTPUT_KEY]
        retrieval_result, evidence_drafts = build_profile_retrieval_result(
            output["context_result"],
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            tool_route_plan=_require_state_value(state["tool_route_plan"], "tool_route_plan"),
            acquisition_result=_require_state_value(
                state["acquisition_result"], "acquisition_result"
            ),
            artifact_id=self._id_factory(),
        )
        self._evidence_store.put(run_id=request.run_id, evidence_drafts=evidence_drafts)
        planning_result = output["planning_result"]
        result = planning_result_from_projection(planning_result)
        answer_draft = (
            validate_answer_draft_v1(result, analysis_result=output["analysis_result"])
            if "answer" in result
            else None
        )
        plan_draft = (
            validate_action_plan_draft_v1(result, analysis_result=output["analysis_result"])
            if "plan_id" in result
            else None
        )
        llm_result = self._review_agent.invoke_inspect_llm(
            request_intent=_require_state_value(state["request_intent"], "request_intent"),
            context_result=output["context_result"],
            analysis_result=output["analysis_result"],
            answer_draft=answer_draft,
            plan_draft=plan_draft,
            request=request,
            deterministic_action_risks=state.get("__modify_review_risks__"),
        )
        review_result = self._review_agent.build_output_from_llm_result(
            llm_result,
            analysis_result=output["analysis_result"],
            answer_draft=answer_draft,
            plan_draft=plan_draft,
        )
        updated_local = dict(record_llm_result(local_state, llm_result))
        updated_local["node_state"] = "SELF_REVIEW_COMPLETE"
        updated_local["typed_result"] = cast(dict[str, object], review_result)
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "context_result": output["context_result"],
            "retrieval_result": retrieval_result,
            "analysis_result": output["analysis_result"],
            **profile_planning_state_update(
                planning_result,
                analysis_result=output["analysis_result"],
                planning_agent=self._planning_agent,
            ),
            "plan_review": review_result,
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="self_review",
                llm_call_id=f"{request.run_id}:profile.single.self_review.initial",
                prompt_ref=self._review_agent.inspect_prompt_ref,
                llm_call_increment=llm_result.structured_output_attempts,
                repair_increment=max(0, llm_result.structured_output_attempts - 1),
            ),
        }

    def _result_validate_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        review_result = _require_state_value(state["plan_review"], "plan_review")
        updated_local = dict(local_state)
        updated_local["node_state"] = "RESULT_VALIDATED"
        updated_local["typed_result"] = review_result
        return {
            **state,
            PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
            "trace_context": merge_trace_context(
                state,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="single_workflow",
                agent_role="unified_agent",
                agent_invocation_id=local_state["invocation_id"],
                subgraph_namespace="single",
                node_name="result_validate",
            ),
        }

    def _finalize_node(self, state: SingleWorkflowLocalState) -> SingleWorkflowLocalState:
        local_state = cast(AgentLocalStateV1, state[PROFILE_AGENT_LOCAL_KEY])
        if state.get("plan_review") is None:
            prompt_output = state[PROFILE_REQUEST_SOURCE_OUTPUT_KEY]
            source_plan = prompt_output["source_plan"]
            if source_plan["result"] == "NEEDS_CONFIRMATION" and isinstance(
                state.get("user_interrupt"), Mapping
            ):
                _response, early_return_patch = self._confirm_inline(state)
                if early_return_patch is not None:
                    return cast(
                        SingleWorkflowLocalState,
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
                    SingleWorkflowLocalState,
                    {
                        **resolved,
                        "user_interrupt": None,
                        "prompt_context": prompt_context,
                        "__profile_request_source_confirmation_resolved__": True,
                    },
                )
            request_intent = _require_state_value(state["request_intent"], "request_intent")
            current: SingleWorkflowLocalState = {
                **state,
                "request_intent": request_intent,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="single_workflow",
                    agent_role="unified_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="single",
                    node_name="finalize",
                ),
            }
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
            merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
            merged.pop(PROFILE_REQUEST_SOURCE_OUTPUT_KEY, None)
            return cast(SingleWorkflowLocalState, merged)
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
                PROFILE_AGENT_LOCAL_KEY: cast(AgentLocalStateV1, updated_local),
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="single_workflow",
                    agent_role="unified_agent",
                    agent_invocation_id=local_state["invocation_id"],
                    subgraph_namespace="single",
                    node_name="finalize",
                ),
            },
            self._review_agent.build_state_update(result),
            decision,
        )
        merged.pop(PROFILE_AGENT_LOCAL_KEY, None)
        merged.pop(PROFILE_REASON_PLAN_OUTPUT_KEY, None)
        return cast(SingleWorkflowLocalState, merged)
