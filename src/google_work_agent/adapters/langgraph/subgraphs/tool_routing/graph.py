"""Canonical Tool Routing owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.graph_state import ParentGraphState, _require_state_value
from google_work_agent.adapters.langgraph.route_translation import RESUME_CONTRACT_VERSION, confirmation_resume_status
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.bind_registry_candidates_node import bind_registry_candidates_node
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.determine_io_resources_node import determine_io_resources_node
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.finalize_route_node import finalize_route_node
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.select_tool_if_needed_node import select_tool_if_needed_node
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.validate_route_node import validate_route_node
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_confirmation import route_after_confirmation
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_determine_io_resources import route_after_determine_io_resources
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.routing.route_after_finalize_route import route_after_finalize_route
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import ToolRoutingInputState, ToolRoutingState
from google_work_agent.application.orchestration.handoff_contracts import (
    ClarificationQuestionV1,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    PolicyConfirmationReceiptV1,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.tool_routing import (
    ScopeExpansionRequiredV1,
    ToolRouteCoordinator,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.application.orchestration.tool_route_semantic import ToolRouteAgent
from google_work_agent.application.orchestration.request_understanding import build_user_interrupt_v1
from google_work_agent.application.orchestration.scope_expansion import build_policy_confirmation_receipt
from google_work_agent.domain import ConnectorToolCatalog

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[[ToolRoutingState], tuple[ConfirmationResponseV1 | None, dict[str, object] | None]]
RecordPolicyConfirmationReceipt = Callable[[str, PolicyConfirmationReceiptV1], None]


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

    def __init__(self, *, coordinator: ToolRouteCoordinator, semantic_agent: ToolRouteAgent, merge_decision: MergeDecision, confirm_inline: ConfirmInline, record_policy_confirmation_receipt: RecordPolicyConfirmationReceipt, id_factory: Callable[[], str]) -> None:
        self._coordinator = coordinator
        self._semantic_agent = semantic_agent
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline
        self._record_policy_confirmation_receipt = record_policy_confirmation_receipt
        self._id_factory = id_factory

    @property
    def _tool_catalog(self):
        return self._semantic_agent._tool_catalog

    def build(self) -> Any:
        graph = StateGraph(ToolRoutingState, input_schema=ToolRoutingInputState, output_schema=ParentGraphState)
        graph.add_node("determine_io_resources", self._determine_io_resources_node)
        graph.add_node("bind_registry_candidates", self._bind_registry_candidates_node)
        graph.add_node("select_tool_if_needed", self._select_tool_if_needed_node)
        graph.add_node("finalize_route", self._finalize_route_node)
        graph.add_node("prepare_confirmation", self._prepare_confirmation_node)
        graph.add_node("confirm", self._confirm_node)
        graph.add_node("validate_route", self._validate_route_node)
        graph.add_edge(START, "determine_io_resources")
        graph.add_conditional_edges("determine_io_resources", route_after_determine_io_resources, {"confirm": "prepare_confirmation", "bind_registry_candidates": "bind_registry_candidates"})
        graph.add_edge("bind_registry_candidates", "select_tool_if_needed")
        graph.add_edge("select_tool_if_needed", "finalize_route")
        graph.add_conditional_edges("finalize_route", route_after_finalize_route, {"confirm": "prepare_confirmation", "validate_route": "validate_route"})
        graph.add_edge("prepare_confirmation", "confirm")
        graph.add_conditional_edges("confirm", route_after_confirmation, {"determine_io_resources": "determine_io_resources", "finalize_route": "finalize_route", "validate_route": "validate_route"})
        graph.add_edge("validate_route", END)
        return graph.compile(name="tool_routing_subgraph")

    def _determine_io_resources_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return determine_io_resources_node(state, llm_runtime=self._semantic_agent._llm_runtime, tool_catalog=self._tool_catalog, prompt_ref=self._semantic_agent._prompt_ref, revision_prompt_ref=self._semantic_agent._determine_io_resources_revision_prompt_ref)

    def _bind_registry_candidates_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return bind_registry_candidates_node(state, tool_catalog=self._tool_catalog, id_factory=self._id_factory)

    def _select_tool_if_needed_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return select_tool_if_needed_node(state, llm_runtime=self._semantic_agent._llm_runtime, prompt_ref=self._semantic_agent._select_tool_prompt_ref, revision_prompt_ref=self._semantic_agent._select_tool_revision_prompt_ref)

    def _finalize_route_node(self, state: ToolRoutingState) -> ToolRoutingState:
        return finalize_route_node(state, tool_catalog=self._tool_catalog, id_factory=self._id_factory, scope_expansion=self._coordinator._scope_expansion)

    def _prepare_confirmation_node(self, state: ToolRoutingState) -> ToolRoutingState:
        result = state.get("tr_result")
        if result is None:
            raise ValueError("tool-routing confirmation result is required")
        request_intent = _require_state_value(state.get("request_intent"), "request_intent")
        signal = result.get("workflow_signal")
        if isinstance(signal, Mapping) and signal.get("kind") == "SCOPE_EXPANSION_REQUIRED":
            typed_signal = cast(ScopeExpansionRequiredV1, signal)
            resources = ", ".join(typed_signal["required_resource_types"])
            question: ClarificationQuestionV1 = {"schema_version": 1, "origin_target": "tool_route.finalize", "question": f"요청한 작업을 처리하려면 {resources} 데이터를 추가 확인해야 합니다. 진행할까요?", "affected_field_paths": ["requested_resource_hints"], "reason_code": typed_signal["reason_codes"][0] if typed_signal["reason_codes"] else "SCOPE_EXPANSION_REQUIRED", "known_context_summary": request_intent["goal"], "options": [{"option_id": "APPROVED", "label": "진행"}, {"option_id": "DECLINED", "label": "진행하지 않음"}]}
            origin = "scope_expansion"
        else:
            question = {"schema_version": 1, "origin_target": "tool_route.determine_io_resources", "question": "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요.", "affected_field_paths": ["requested_resource_hints", "requested_effect_hints"], "reason_code": result["reason_codes"][0] if result["reason_codes"] else "TOOL_ROUTE_NEEDS_CONFIRMATION", "known_context_summary": request_intent["goal"], "options": []}
            origin = "semantic"
        interrupt_id = self._id_factory()
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context["confirmation_interrupt"] = {"schema_version": 1, "interrupt_id": interrupt_id, "owner_subgraph": "TOOL_ROUTE", "origin_target": question["origin_target"], "resume_target": {"subgraph_id": "TOOL_ROUTE", "node_id": "confirm", "graph_version": RESUME_CONTRACT_VERSION}, "resume_status": confirmation_resume_status("TOOL_ROUTE").value}
        return {"workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value, "user_interrupt": {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id}, "prompt_context": prompt_context, "tr_confirmation_origin": origin, "tr_current_interrupt_id": interrupt_id}

    def _confirm_node(self, state: ToolRoutingState) -> ToolRoutingState:
        confirmation_response, early_return_patch = self._confirm_inline(state)
        if early_return_patch is not None:
            return cast(ToolRoutingState, {**state, **early_return_patch})
        if confirmation_response is None:
            raise ValueError("tool-routing confirmation response is required")
        prompt_context = dict(cast(dict[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_interrupt", None)
        if state.get("tr_confirmation_origin") != "scope_expansion":
            return {"tr_confirmation_response": confirmation_response, "user_interrupt": None, "prompt_context": prompt_context}
        result = _require_state_value(state.get("tr_result"), "tr_result")
        signal = cast(ScopeExpansionRequiredV1, result["workflow_signal"])
        interrupt_id = _require_state_value(state.get("tr_current_interrupt_id"), "tr_current_interrupt_id")
        decision: Literal["APPROVED", "DECLINED"] = "APPROVED" if confirmation_response["selected_option_ids"] == ["APPROVED"] else "DECLINED"
        request_intent = _require_state_value(state.get("request_intent"), "request_intent")
        receipt = build_policy_confirmation_receipt(id_factory=self._id_factory, interrupt_id=interrupt_id, decision=decision, request_intent=request_intent, required_resource_types=tuple(signal["required_resource_types"]), reason_codes=tuple(signal["reason_codes"]), affected_route_ids=_scope_expansion_affected_route_ids(signal["required_resource_types"]))
        self._record_policy_confirmation_receipt(cast(str, state["run_id"]), receipt)
        receipts = [*cast(list[PolicyConfirmationReceiptV1], state.get("policy_confirmation_receipts", [])), receipt]
        if decision == "DECLINED":
            return {"policy_confirmation_receipts": receipts, "user_interrupt": None, "prompt_context": prompt_context, "tr_result": {"schema_version": 1, "disposition": "BLOCKED", "tool_route_plan": None, "workflow_signal": None, "reason_codes": ["SCOPE_EXPANSION_DECLINED"]}}
        return {"policy_confirmation_receipts": receipts, "user_interrupt": None, "prompt_context": prompt_context}

    def _validate_route_node(self, state: ToolRoutingState) -> ToolRoutingState:
        patch = validate_route_node(state, tool_catalog=self._tool_catalog)
        result = _require_state_value(state.get("tr_result"), "tr_result")
        decision = route_supervisor(phase=WorkflowPhase.TOOL_ROUTING, state=cast(MultiAgentGraphState, {**state, **patch}), result=result)
        merged = self._merge_decision({**state, **patch, "retry_budget": state.get("tr_retry_budget", state["retry_budget"])}, {"workflow_phase": WorkflowPhase.TOOL_ROUTING.value}, decision)
        for key in ("tr_semantic_candidate", "tr_selected_tools", "tr_binding", "tr_result", "tr_confirmation_response", "tr_retry_budget", "tr_confirmation_origin", "tr_current_interrupt_id"):
            merged.pop(key, None)
        return cast(ToolRoutingState, merged)


def build_tool_routing_subgraph(
    *,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    merge_decision: MergeDecision,
    semantic_agent: ToolRouteAgent,
    confirm_inline: ConfirmInline,
    record_policy_confirmation_receipt: RecordPolicyConfirmationReceipt,
) -> Any:
    return ToolRoutingSubgraph(
        coordinator=ToolRouteCoordinator(tool_catalog=tool_catalog, id_factory=id_factory),
        semantic_agent=semantic_agent,
        merge_decision=merge_decision,
        confirm_inline=confirm_inline,
        record_policy_confirmation_receipt=record_policy_confirmation_receipt,
        id_factory=id_factory,
    ).build()
