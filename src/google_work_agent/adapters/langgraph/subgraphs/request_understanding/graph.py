"""Canonical Request Understanding owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import merge_trace_context
from google_work_agent.adapters.langgraph.main.state import ParentGraphState, request_from_state
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.detect_ambiguity_node import (
    detect_ambiguity_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.finalize_intent_node import (
    finalize_intent_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.identify_goal_node import (
    identify_goal_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.validate_intent_node import (
    validate_intent_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing.route_after_detect_ambiguity import (
    route_after_detect_ambiguity,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingInputState,
    RequestUnderstandingState,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ClarificationQuestionV1,
)
from google_work_agent.application.orchestration.request_understanding import (
    RequestUnderstandingAgent,
    build_user_interrupt_v1,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [RequestUnderstandingState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class RequestUnderstandingSubgraph:
    """Compile the four canonical Request Understanding operations."""

    def __init__(
        self,
        *,
        agent: RequestUnderstandingAgent,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            RequestUnderstandingState,
            input_schema=RequestUnderstandingInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("initialize", self._initialize_node)
        graph.add_node("identify_goal", self._identify_goal_node)
        graph.add_node("detect_ambiguity", self._detect_ambiguity_node)
        graph.add_node("prepare_confirmation", self._prepare_confirmation_node)
        graph.add_node("confirm", self._confirm_node)
        graph.add_node("finalize_intent", self._finalize_intent_node)
        graph.add_node("validate_intent", self._validate_intent_node)
        graph.add_edge(START, "initialize")
        graph.add_edge("initialize", "identify_goal")
        graph.add_edge("identify_goal", "detect_ambiguity")
        graph.add_conditional_edges(
            "detect_ambiguity",
            route_after_detect_ambiguity,
            {"confirm": "prepare_confirmation", "finalize_intent": "finalize_intent"},
        )
        graph.add_edge("prepare_confirmation", "confirm")
        graph.add_edge("confirm", "identify_goal")
        graph.add_edge("finalize_intent", "validate_intent")
        graph.add_edge("validate_intent", END)
        return graph.compile(name="request_understanding_subgraph")

    def _initialize_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        invocation_id = self._id_factory()
        return cast(
            RequestUnderstandingState,
            {
                **state,
                "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value,
                "ru_invocation_id": invocation_id,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="request_understanding",
                    agent_role="request_understanding",
                    agent_invocation_id=invocation_id,
                    subgraph_namespace="request_understanding",
                    node_name="init",
                    prompt_ref=self._agent.prompt_ref,
                    agent_invocation_increment=1,
                ),
            },
        )

    def _identify_goal_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        patch = identify_goal_node(
            state,
            llm_runtime=self._agent._llm_runtime,
            prompt_ref=self._agent.prompt_ref,
        )
        request = request_from_state(state)
        return {
            **patch,
            "trace_context": self._trace(
                state,
                node_name="identify_goal",
                llm_call_id=f"{request.run_id}:request_understanding.classify",
                prompt_ref=self._agent.prompt_ref,
                llm_call_increment=1,
            ),
        }

    def _detect_ambiguity_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        return {
            **detect_ambiguity_node(state),
            "trace_context": self._trace(state, node_name="detect_ambiguity"),
        }

    def _prepare_confirmation_node(
        self, state: RequestUnderstandingState
    ) -> RequestUnderstandingState:
        ambiguity = state.get("ru_ambiguity")
        candidate = state.get("ru_candidate")
        if ambiguity is None or candidate is None:
            raise ValueError("request-understanding ambiguity is required")
        missing = ", ".join(ambiguity["missing_fields"])
        question: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "request_understanding.classify",
            "question": f"다음 정보를 더 알려주세요: {missing}"
            if missing
            else "요청을 더 구체적으로 알려주세요.",
            "affected_field_paths": list(ambiguity["missing_fields"]),
            "reason_code": ambiguity["reason_codes"][0]
            if ambiguity["reason_codes"]
            else "REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION",
            "known_context_summary": candidate["goal"],
            "options": [],
        }
        question["question"] = (
            f"다음 정보를 더 알려주세요: {missing}"
            if missing
            else "요청을 더 구체적으로 알려주세요."
        )
        interrupt_id = self._id_factory()
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "REQUEST_UNDERSTANDING",
            "origin_target": question["origin_target"],
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": {
                **build_user_interrupt_v1(question),
                "interrupt_id": interrupt_id,
            },
            "prompt_context": prompt_context,
            "trace_context": self._trace(state, node_name="prepare_confirmation"),
        }

    def _confirm_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                RequestUnderstandingState,
                {
                    **state,
                    **early_return_patch,
                    "trace_context": self._trace(state, node_name="confirm"),
                },
            )
        if confirmation_response is None:
            raise ValueError("request-understanding confirmation response is required")
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        return {
            "ru_confirmation_response": confirmation_response,
            "user_interrupt": None,
            "prompt_context": prompt_context,
            "trace_context": self._trace(state, node_name="confirm"),
        }

    def _finalize_intent_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        return {
            **finalize_intent_node(state, id_factory=self._id_factory),
            "trace_context": self._trace(state, node_name="finalize_intent"),
        }

    def _validate_intent_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        patch = validate_intent_node(state)
        intent = patch["request_intent"]
        output = {
            "schema_version": 1,
            "result": "COMPLETE",
            "request_intent": intent,
            "clarification": None,
            "failure": None,
            "validator_codes": [],
        }
        decision = route_supervisor(
            phase=WorkflowPhase.REQUEST_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=output,
        )
        update = self._agent.build_state_update(output, request=request_from_state(state))
        traced_state = {
            **state,
            **patch,
            "trace_context": self._trace(state, node_name="validate_intent"),
        }
        merged = self._merge_decision(traced_state, update, decision)
        for key in (
            "ru_candidate",
            "ru_ambiguity",
            "ru_intent",
            "ru_confirmation_response",
            "ru_invocation_id",
        ):
            merged.pop(key, None)
        return cast(RequestUnderstandingState, merged)

    def _trace(
        self,
        state: RequestUnderstandingState,
        *,
        node_name: str,
        llm_call_id: str | None = None,
        prompt_ref: Any = None,
        llm_call_increment: int = 0,
    ) -> dict[str, object]:
        invocation_id = state.get("ru_invocation_id")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ValueError("request-understanding invocation id is required")
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="request_understanding",
            agent_role="request_understanding",
            agent_invocation_id=invocation_id,
            subgraph_namespace="request_understanding",
            node_name=node_name,
            llm_call_id=llm_call_id,
            prompt_ref=prompt_ref,
            llm_call_increment=llm_call_increment,
        )
