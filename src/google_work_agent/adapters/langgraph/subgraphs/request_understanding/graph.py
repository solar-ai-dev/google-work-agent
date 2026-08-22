"""Canonical Request Understanding owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.graph_state import ParentGraphState, request_from_state
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.route_translation import RESUME_CONTRACT_VERSION, confirmation_resume_status
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.detect_ambiguity_node import detect_ambiguity_node
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.finalize_intent_node import finalize_intent_node
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.identify_goal_node import identify_goal_node
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.validate_intent_node import validate_intent_node
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing.route_after_detect_ambiguity import route_after_detect_ambiguity
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import RequestUnderstandingInputState, RequestUnderstandingState
from google_work_agent.application.workflows import ClarificationQuestionV1, ConfirmationResponseV1, GraphStateUpdateV1, MultiAgentGraphState, RequestUnderstandingAgent, SupervisorDecisionV1, WorkflowPhase, route_supervisor
from google_work_agent.application.workflows.request_understanding import build_user_interrupt_v1

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[[RequestUnderstandingState], tuple[ConfirmationResponseV1 | None, dict[str, object] | None]]


class RequestUnderstandingSubgraph:
    """Compile the four canonical Request Understanding operations."""

    def __init__(self, *, agent: RequestUnderstandingAgent, id_factory: Callable[[], str], graph_profile: GraphProfile, transition_run: TransitionRun, merge_decision: MergeDecision, confirm_inline: ConfirmInline) -> None:
        self._agent = agent
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(RequestUnderstandingState, input_schema=RequestUnderstandingInputState, output_schema=ParentGraphState)
        graph.add_node("initialize", self._initialize_node)
        graph.add_node("identify_goal", self._identify_goal_node)
        graph.add_node("detect_ambiguity", detect_ambiguity_node)
        graph.add_node("prepare_confirmation", self._prepare_confirmation_node)
        graph.add_node("confirm", self._confirm_node)
        graph.add_node("finalize_intent", self._finalize_intent_node)
        graph.add_node("validate_intent", self._validate_intent_node)
        graph.add_edge(START, "initialize")
        graph.add_edge("initialize", "identify_goal")
        graph.add_edge("identify_goal", "detect_ambiguity")
        graph.add_conditional_edges("detect_ambiguity", route_after_detect_ambiguity, {"confirm": "prepare_confirmation", "finalize_intent": "finalize_intent"})
        graph.add_edge("prepare_confirmation", "confirm")
        graph.add_edge("confirm", "identify_goal")
        graph.add_edge("finalize_intent", "validate_intent")
        graph.add_edge("validate_intent", END)
        return graph.compile(name="request_understanding_subgraph")

    def _initialize_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        request = request_from_state(state)
        self._transition_run(request.run_id, "start_analysis")
        return cast(RequestUnderstandingState, {**state, "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value})

    def _identify_goal_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        return identify_goal_node(state, llm_runtime=self._agent._llm_runtime, prompt_ref=self._agent.prompt_ref)

    def _prepare_confirmation_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        ambiguity = state.get("ru_ambiguity")
        candidate = state.get("ru_candidate")
        if ambiguity is None or candidate is None:
            raise ValueError("request-understanding ambiguity is required")
        missing = ", ".join(ambiguity["missing_fields"])
        question: ClarificationQuestionV1 = {"schema_version": 1, "origin_target": "request_understanding.detect_ambiguity", "question": f"다음 정보를 더 알려주세요: {missing}" if missing else "요청을 더 구체적으로 알려주세요.", "affected_field_paths": list(ambiguity["missing_fields"]), "reason_code": ambiguity["reason_codes"][0] if ambiguity["reason_codes"] else "REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION", "known_context_summary": candidate["goal"], "options": []}
        interrupt_id = self._id_factory()
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context["confirmation_interrupt"] = {"schema_version": 1, "interrupt_id": interrupt_id, "owner_subgraph": "REQUEST_UNDERSTANDING", "origin_target": question["origin_target"], "resume_target": {"subgraph_id": "REQUEST_UNDERSTANDING", "node_id": "confirm", "graph_version": RESUME_CONTRACT_VERSION}, "resume_status": confirmation_resume_status("REQUEST_UNDERSTANDING").value}
        return {"workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value, "user_interrupt": {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id}, "prompt_context": prompt_context}

    def _confirm_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(RequestUnderstandingState, {**state, **early_return_patch})
        if confirmation_response is None:
            raise ValueError("request-understanding confirmation response is required")
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        return {"ru_confirmation_response": confirmation_response, "user_interrupt": None, "prompt_context": prompt_context}

    def _finalize_intent_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        return finalize_intent_node(state, id_factory=self._id_factory)

    def _validate_intent_node(self, state: RequestUnderstandingState) -> RequestUnderstandingState:
        patch = validate_intent_node(state)
        intent = patch["request_intent"]
        output = {"schema_version": 1, "result": "COMPLETE", "request_intent": intent, "clarification": None, "failure": None, "validator_codes": []}
        decision = route_supervisor(phase=WorkflowPhase.REQUEST_ANALYSIS, state=cast(MultiAgentGraphState, state), result=output)
        update = self._agent.build_state_update(output, request=request_from_state(state))
        merged = self._merge_decision({**state, **patch}, update, decision)
        for key in ("ru_candidate", "ru_ambiguity", "ru_intent", "ru_confirmation_response"):
            merged.pop(key, None)
        return cast(RequestUnderstandingState, merged)
