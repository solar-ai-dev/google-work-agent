"""Canonical Request Understanding owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import merge_trace_context
from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
    request_from_run_input_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.detect_ambiguity_node import (  # noqa: E501
    detect_ambiguity_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.finalize_intent_node import (  # noqa: E501
    finalize_intent_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.nodes.identify_goal_node import (  # noqa: E501
    identify_goal_node,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing.route_after_detect_ambiguity import (  # noqa: E501
    route_after_detect_ambiguity,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing.route_after_finalize_intent import (  # noqa: E501
    route_after_finalize_intent,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.routing.route_after_identify_goal import (  # noqa: E501
    route_after_identify_goal,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingInputState,
    RequestUnderstandingParentOutputState,
    RequestUnderstandingStateV2,
)
from google_work_agent.application.agents.request_understanding.contracts.request_understanding_output import (  # noqa: E501
    ClarificationQuestionV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    UserInterruptV1,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [RequestUnderstandingStateV2],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class RequestUnderstandingSubgraph:
    """Compile the exact three runtime nodes for four canonical operations."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        prompt_manifest_path: Path | None,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._identify_goal_prompt_ref = load_prompt_reference(
            "request_understanding.identify_goal", manifest_path
        )
        self._detect_ambiguity_prompt_ref = load_prompt_reference(
            "request_understanding.detect_ambiguity", manifest_path
        )
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            RequestUnderstandingStateV2,
            input_schema=RequestUnderstandingInputState,
            output_schema=RequestUnderstandingParentOutputState,
        )
        graph.add_node("identify_goal", self._identify_goal_node)
        graph.add_node("detect_ambiguity", self._detect_ambiguity_node)
        graph.add_node("finalize_intent", self._finalize_intent_node)
        graph.add_edge(START, "identify_goal")
        graph.add_conditional_edges(
            "identify_goal",
            route_after_identify_goal,
            {"detect_ambiguity": "detect_ambiguity"},
        )
        graph.add_conditional_edges(
            "detect_ambiguity",
            route_after_detect_ambiguity,
            {"finalize_intent": "finalize_intent"},
        )
        graph.add_conditional_edges(
            "finalize_intent",
            route_after_finalize_intent,
            {"identify_goal": "identify_goal", "end": END},
        )
        return graph.compile(name="request_understanding_subgraph")

    def _identify_goal_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        request = request_from_run_input_state(cast(Any, state))
        invocation_id = self._invocation_id(state)
        is_first_node = invocation_id is None
        if is_first_node:
            self._transition_run(request.run_id, "start_analysis")
            invocation_id = self._id_factory()
        if request.entry_mode not in {"AGENT_SEARCH", "RESOURCE_SELECTED"}:
            raise ValueError(f"unsupported request entry mode: {request.entry_mode}")
        current_run_fields = cast(
            RequestUnderstandingStateV2,
            {
                "request_text": request.request_text,
                "entry_mode": request.entry_mode,
                "selected_resource_refs": list(request.selected_resources),
            },
        )
        working_state = cast(RequestUnderstandingStateV2, {**state, **current_run_fields})
        patch = identify_goal_node(
            working_state,
            llm_runtime=self._llm_runtime,
            prompt_ref=self._identify_goal_prompt_ref,
        )
        return {
            **current_run_fields,
            **patch,
            "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value,
            "trace_context": self._trace(
                working_state,
                node_name="identify_goal",
                llm_call_id=f"{request.run_id}:request.identify_goal",
                prompt_ref=self._identify_goal_prompt_ref,
                llm_call_increment=1,
                invocation_id=invocation_id,
                agent_invocation_increment=1 if is_first_node else 0,
            ),
        }

    def _detect_ambiguity_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        request = request_from_run_input_state(cast(Any, state))
        patch = detect_ambiguity_node(
            state,
            llm_runtime=self._llm_runtime,
            prompt_ref=self._detect_ambiguity_prompt_ref,
        )
        working_state = cast(RequestUnderstandingStateV2, {**state, **patch})
        result: RequestUnderstandingStateV2 = {
            **patch,
            "trace_context": self._trace(
                state,
                node_name="detect_ambiguity",
                llm_call_id=f"{request.run_id}:request.detect_ambiguity",
                prompt_ref=self._detect_ambiguity_prompt_ref,
                llm_call_increment=1,
            ),
        }
        ambiguity = working_state.get("ambiguity_candidate")
        if ambiguity is not None and ambiguity["requires_confirmation"]:
            result.update(self._confirmation_signal(working_state))
        return result

    def _confirmation_signal(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        ambiguity = state.get("ambiguity_candidate")
        candidate = state.get("goal_candidate")
        if ambiguity is None or candidate is None:
            raise ValueError("request-understanding ambiguity is required")
        missing = ", ".join(ambiguity["missing_fields"])
        question: ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "request.detect_ambiguity",
            "question": (
                f"Please clarify the following request fields: {missing}"
                if missing
                else "Please clarify the request."
            ),
            "affected_field_paths": list(ambiguity["missing_fields"]),
            "reason_code": (
                ambiguity["reason_codes"][0]
                if ambiguity["reason_codes"]
                else "REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"
            ),
            "known_context_summary": candidate["goal"],
            "options": [],
        }
        interrupt_id = self._id_factory()
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_response", None)
        prompt_context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "REQUEST_UNDERSTANDING",
            "origin_target": question["origin_target"],
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": cast(
                UserInterruptV1,
                {
                    **build_user_interrupt_v1(question),
                    "interrupt_id": interrupt_id,
                },
            ),
            "prompt_context": prompt_context,
        }

    def _finalize_intent_node(
        self, state: RequestUnderstandingStateV2
    ) -> RequestUnderstandingStateV2:
        ambiguity = state.get("ambiguity_candidate")
        if ambiguity is None:
            raise ValueError("request-understanding ambiguity result is required")
        if ambiguity["requires_confirmation"]:
            confirmation_response, early_return_patch = self._confirm_inline(state)
            trace_context = self._trace(state, node_name="finalize_intent")
            if early_return_patch is not None:
                return cast(
                    RequestUnderstandingStateV2,
                    {
                        **early_return_patch,
                        "user_interrupt": None,
                        "trace_context": trace_context,
                    },
                )
            if confirmation_response is None:
                raise ValueError("request-understanding confirmation response is required")
            prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
            prompt_context["confirmation_response"] = dict(confirmation_response)
            prompt_context.pop("confirmation_interrupt", None)
            return {
                "final_intent": None,
                "request_intent": None,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "trace_context": trace_context,
            }

        patch = finalize_intent_node(state, id_factory=self._id_factory)
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
        request = request_from_run_input_state(cast(Any, state))
        update: GraphStateUpdateV1 = {
            "request_intent": intent,
            "workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value,
            "prompt_context": {
                "entry_mode": request.entry_mode,
                "selected_resource_ids": list(request.selected_resource_ids),
            },
            "trace_context": {
                "request_understanding_result": "COMPLETE",
                "validator_codes": [],
            },
        }
        traced_state = cast(
            RequestUnderstandingStateV2,
            {
                **state,
                **patch,
                "trace_context": self._trace(state, node_name="finalize_intent"),
            },
        )
        merged = self._merge_decision(traced_state, update, decision)
        merged["final_intent"] = intent
        return cast(RequestUnderstandingStateV2, merged)

    def _trace(
        self,
        state: RequestUnderstandingStateV2,
        *,
        node_name: str,
        llm_call_id: str | None = None,
        prompt_ref: Any = None,
        llm_call_increment: int = 0,
        invocation_id: str | None = None,
        agent_invocation_increment: int = 0,
    ) -> dict[str, object]:
        resolved_invocation_id = invocation_id or self._invocation_id(state)
        if resolved_invocation_id is None:
            raise ValueError("request-understanding invocation id is required")
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="request_understanding",
            agent_role="request_understanding",
            agent_invocation_id=resolved_invocation_id,
            subgraph_namespace="request_understanding",
            node_name=node_name,
            llm_call_id=llm_call_id,
            prompt_ref=prompt_ref,
            agent_invocation_increment=agent_invocation_increment,
            llm_call_increment=llm_call_increment,
        )

    @staticmethod
    def _invocation_id(state: RequestUnderstandingStateV2) -> str | None:
        trace_context = state.get("trace_context", {})
        raw_log = trace_context.get("agent_node_log", [])
        if not isinstance(raw_log, list):
            return None
        for item in reversed(raw_log):
            if not isinstance(item, Mapping):
                continue
            if item.get("agent_subgraph_id") != "request_understanding":
                continue
            invocation_id = item.get("agent_invocation_id")
            if isinstance(invocation_id, str) and invocation_id:
                return invocation_id
        return None


__all__ = ["RequestUnderstandingSubgraph"]
