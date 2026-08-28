"""Canonical Tool Routing owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import merge_trace_context
from google_work_agent.adapters.langgraph.main.state import (
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.bind_registry_candidates_node import (  # noqa: E501
    bind_registry_candidates_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.determine_io_resources_node import (  # noqa: E501
    determine_io_resources_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.finalize_route_node import (
    finalize_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.select_tool_if_needed_node import (  # noqa: E501
    select_tool_if_needed_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.validate_route_node import (
    validate_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_confirmation import (  # noqa: E501
    route_after_confirmation,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_determine_io_resources import (  # noqa: E501
    route_after_determine_io_resources,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_finalize_route import (  # noqa: E501
    route_after_finalize_route,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import (
    ToolRoutingInputState,
    ToolRoutingState,
)
from google_work_agent.application.orchestration.confirmation import (
    build_user_interrupt_v1,
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
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.orchestration.tool_route_semantic import ToolRouteAgent
from google_work_agent.application.orchestration.tool_routing import (
    ScopeExpansionRequiredV1,
    ToolRouteCoordinator,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ToolRoutingState], tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]
]


def _scope_expansion_affected_route_ids(resource_types: list[str]) -> list[str]:
    affected: set[str] = set()
    for resource_type in resource_types:
        if resource_type in {"TASK", "TASK_LIST"}:
            affected.add("TASK:CREATE")
        elif resource_type.startswith("CALENDAR"):
            affected.add("CALENDAR_EVENT:CREATE")
    return sorted(affected)


class ToolRoutingSubgraph:
    """Compile the five canonical Tool Routing operations."""

    def __init__(
        self,
        *,
        coordinator: ToolRouteCoordinator,
        semantic_agent: ToolRouteAgent,
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
        id_factory: Callable[[], str],
    ) -> None:
        self._coordinator = coordinator
        self._semantic_agent = semantic_agent
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline
        self._id_factory = id_factory

    @property
    def _tool_catalog(self):
        return self._semantic_agent._tool_catalog

    def build(self) -> Any:
        graph = StateGraph(
            ToolRoutingState, input_schema=ToolRoutingInputState, output_schema=ParentGraphState
        )
        graph.add_node("initialize", self._initialize_node)
        graph.add_node("determine_io_resources", self._determine_io_resources_node)
        graph.add_node("bind_registry_candidates", self._bind_registry_candidates_node)
        graph.add_node("select_tool_if_needed", self._select_tool_if_needed_node)
        graph.add_node("finalize_route", self._finalize_route_node)
        graph.add_node("prepare_confirmation", self._prepare_confirmation_node)
        graph.add_node("confirm", self._confirm_node)
        graph.add_node("validate_route", self._validate_route_node)
        graph.add_edge(START, "initialize")
        graph.add_edge("initialize", "determine_io_resources")
        graph.add_conditional_edges(
            "determine_io_resources",
            route_after_determine_io_resources,
            {
                "confirm": "prepare_confirmation",
                "bind_registry_candidates": "bind_registry_candidates",
            },
        )
        graph.add_edge("bind_registry_candidates", "select_tool_if_needed")
        graph.add_edge("select_tool_if_needed", "finalize_route")
        graph.add_conditional_edges(
            "finalize_route",
            route_after_finalize_route,
            {"confirm": "prepare_confirmation", "validate_route": "validate_route"},
        )
        graph.add_edge("prepare_confirmation", "confirm")
        graph.add_conditional_edges(
            "confirm",
            route_after_confirmation,
            {
                "determine_io_resources": "determine_io_resources",
                "finalize_route": "finalize_route",
                "validate_route": "validate_route",
            },
        )
        graph.add_edge("validate_route", END)
        return graph.compile(name="tool_routing_subgraph")

    def _initialize_node(self, state: ToolRoutingState) -> ToolRoutingState:
        invocation_id = self._id_factory()
        return cast(
            ToolRoutingState,
            {
                **state,
                "tr_invocation_id": invocation_id,
                "trace_context": merge_trace_context(
                    state,
                    graph_profile=self._graph_profile.value,
                    agent_subgraph_id="tool_route",
                    agent_role="tool_routing",
                    agent_invocation_id=invocation_id,
                    subgraph_namespace="tool_routing",
                    node_name="init",
                    prompt_ref=self._semantic_agent._prompt_ref,
                    agent_invocation_increment=1,
                ),
            },
        )

    def _determine_io_resources_node(self, state: ToolRoutingState) -> ToolRoutingState:
        patch = determine_io_resources_node(
            state,
            llm_runtime=self._semantic_agent._llm_runtime,
            tool_catalog=self._tool_catalog,
            prompt_ref=self._semantic_agent._prompt_ref,
            revision_prompt_ref=self._semantic_agent._determine_io_resources_revision_prompt_ref,
        )
        request = request_from_state(state)
        return {
            **patch,
            "trace_context": self._trace(
                state,
                node_name="determine_io_resources",
                llm_call_id=f"{request.run_id}:tool_route.determine_io_resources",
                prompt_ref=self._semantic_agent._prompt_ref,
                llm_call_increment=1,
            ),
        }

    def _bind_registry_candidates_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return {
            **bind_registry_candidates_node(
                state, tool_catalog=self._tool_catalog, id_factory=self._id_factory
            ),
            "trace_context": self._trace(state, node_name="bind_registry_candidates"),
        }

    def _select_tool_if_needed_node(self, state: ToolRoutingState) -> ToolRoutingState:
        binding = _require_state_value(state.get("tr_binding"), "tr_binding")
        llm_call_count = sum(
            len(candidate.eligible_tool_ids) != 1 for candidate in binding.output_candidates
        )
        request = request_from_state(state)
        return {
            **select_tool_if_needed_node(
                state,
                llm_runtime=self._semantic_agent._llm_runtime,
                prompt_ref=self._semantic_agent._select_tool_prompt_ref,
                revision_prompt_ref=self._semantic_agent._select_tool_revision_prompt_ref,
            ),
            "trace_context": self._trace(
                state,
                node_name="select_tool_if_needed",
                llm_call_id=(
                    f"{request.run_id}:tool_route.select_tool_if_needed" if llm_call_count else None
                ),
                prompt_ref=(
                    self._semantic_agent._select_tool_prompt_ref if llm_call_count else None
                ),
                llm_call_increment=llm_call_count,
            ),
        }

    def _finalize_route_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return {
            **finalize_route_node(
                state,
                tool_catalog=self._tool_catalog,
                id_factory=self._id_factory,
                scope_expansion=self._coordinator._scope_expansion,
            ),
            "trace_context": self._trace(state, node_name="finalize_route"),
        }

    def _prepare_confirmation_node(self, state: ToolRoutingState) -> ToolRoutingState:
        result = state.get("tr_result")
        if result is None:
            raise ValueError("tool-routing confirmation result is required")
        request_intent = _require_state_value(state.get("request_intent"), "request_intent")
        signal = result.get("workflow_signal")
        if isinstance(signal, Mapping) and signal.get("kind") == "SCOPE_EXPANSION_REQUIRED":
            typed_signal = cast(ScopeExpansionRequiredV1, signal)
            resources = ", ".join(typed_signal["required_resource_types"])
            question: ClarificationQuestionV1 = {
                "schema_version": 1,
                "origin_target": "tool_route.finalize",
                "question": (
                    f"요청한 작업을 처리하려면 {resources} 데이터를 "
                    "추가 확인해야 합니다. 진행할까요?"
                ),
                "affected_field_paths": ["requested_resource_hints"],
                "reason_code": typed_signal["reason_codes"][0]
                if typed_signal["reason_codes"]
                else "SCOPE_EXPANSION_REQUIRED",
                "known_context_summary": request_intent["goal"],
                "options": [
                    {"option_id": "APPROVED", "label": "진행"},
                    {"option_id": "DECLINED", "label": "진행하지 않음"},
                ],
            }
            origin = "scope_expansion"
        else:
            question = {
                "schema_version": 1,
                "origin_target": "tool_route.finalize",
                "question": "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요.",
                "affected_field_paths": ["requested_resource_hints", "requested_effect_hints"],
                "reason_code": result["reason_codes"][0]
                if result["reason_codes"]
                else "TOOL_ROUTE_NEEDS_CONFIRMATION",
                "known_context_summary": request_intent["goal"],
                "options": [],
            }
            origin = "semantic"
        if origin == "scope_expansion":
            question["question"] = (
                f"요청한 작업을 처리하려면 {resources} 데이터 범위를 "
                "추가로 확인해야 합니다. 진행할까요?"
            )
            question["options"] = [
                {"option_id": "APPROVED", "label": "네, 확인하고 진행합니다"},
                {"option_id": "DECLINED", "label": "아니요, 진행하지 않습니다"},
            ]
        else:
            question["question"] = "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요."
        interrupt_id = self._id_factory()
        raw_interrupt = {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id}
        if origin == "scope_expansion":
            signal = cast(ScopeExpansionRequiredV1, result["workflow_signal"])
            raw_interrupt["policy_confirmation"] = {
                "confirmation_kind": "SCOPE_EXPANSION",
                "request_intent": request_intent,
                "required_resource_types": list(signal["required_resource_types"]),
                "reason_codes": list(signal["reason_codes"]),
                "affected_route_ids": _scope_expansion_affected_route_ids(
                    signal["required_resource_types"]
                ),
            }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": raw_interrupt,
            "tr_confirmation_origin": origin,
            "tr_current_interrupt_id": interrupt_id,
            "trace_context": self._trace(state, node_name="prepare_confirmation"),
        }

    def _confirm_node(self, state: ToolRoutingState) -> ToolRoutingState:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(
                ToolRoutingState,
                {
                    **state,
                    **early_return_patch,
                    "trace_context": self._trace(state, node_name="confirm"),
                },
            )
        if confirmation_response is None:
            raise ValueError("tool-routing confirmation response is required")
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        receipts = list(state.get("policy_confirmation_receipts", []))
        if state.get("tr_confirmation_origin") != "scope_expansion":
            return {
                "tr_confirmation_response": confirmation_response,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "trace_context": self._trace(state, node_name="confirm"),
            }
        decision = (
            "APPROVED"
            if confirmation_response["response_kind"] == "OPTION"
            and confirmation_response["selected_option"] == "APPROVED"
            else "DECLINED"
        )
        if decision == "DECLINED":
            return {
                "policy_confirmation_receipts": receipts,
                "user_interrupt": None,
                "prompt_context": prompt_context,
                "tr_result": {
                    "schema_version": 1,
                    "disposition": "BLOCKED",
                    "tool_route_plan": None,
                    "workflow_signal": None,
                    "reason_codes": ["SCOPE_EXPANSION_DECLINED"],
                },
                "trace_context": self._trace(state, node_name="confirm"),
            }
        return {
            "policy_confirmation_receipts": receipts,
            "user_interrupt": None,
            "prompt_context": prompt_context,
            "trace_context": self._trace(state, node_name="confirm"),
        }

    def _validate_route_node(self, state: ToolRoutingState) -> ToolRoutingState:
        patch = validate_route_node(state, tool_catalog=self._tool_catalog)
        result = _require_state_value(state.get("tr_result"), "tr_result")
        decision = route_supervisor(
            phase=WorkflowPhase.TOOL_ROUTING,
            state=cast(MultiAgentGraphState, {**state, **patch}),
            result=result,
        )
        traced_state = {
            **state,
            **patch,
            "retry_budget": state.get("tr_retry_budget", state["retry_budget"]),
            "trace_context": self._trace(state, node_name="validate_route"),
        }
        merged = self._merge_decision(
            traced_state, {"workflow_phase": WorkflowPhase.TOOL_ROUTING.value}, decision
        )
        for key in (
            "tr_semantic_candidate",
            "tr_selected_tools",
            "tr_binding",
            "tr_result",
            "tr_confirmation_response",
            "tr_retry_budget",
            "tr_confirmation_origin",
            "tr_current_interrupt_id",
            "tr_invocation_id",
        ):
            merged.pop(key, None)
        return cast(ToolRoutingState, merged)

    def _trace(
        self,
        state: ToolRoutingState,
        *,
        node_name: str,
        llm_call_id: str | None = None,
        prompt_ref: Any = None,
        llm_call_increment: int = 0,
    ) -> dict[str, object]:
        invocation_id = state.get("tr_invocation_id")
        if not isinstance(invocation_id, str) or not invocation_id:
            raise ValueError("tool-routing invocation id is required")
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="tool_route",
            agent_role="tool_routing",
            agent_invocation_id=invocation_id,
            subgraph_namespace="tool_routing",
            node_name=node_name,
            llm_call_id=llm_call_id,
            prompt_ref=prompt_ref,
            llm_call_increment=llm_call_increment,
        )


def build_tool_routing_subgraph(
    *,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
    merge_decision: MergeDecision,
    semantic_agent: ToolRouteAgent,
    graph_profile: GraphProfile,
    confirm_inline: ConfirmInline,
) -> Any:
    return ToolRoutingSubgraph(
        coordinator=ToolRouteCoordinator(tool_catalog=tool_catalog, id_factory=id_factory),
        semantic_agent=semantic_agent,
        graph_profile=graph_profile,
        merge_decision=merge_decision,
        confirm_inline=confirm_inline,
        id_factory=id_factory,
    ).build()
