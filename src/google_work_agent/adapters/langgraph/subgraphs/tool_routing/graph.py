"""Canonical Tool Routing owner-local LangGraph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import merge_trace_context
from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.finalize_route_node import (
    finalize_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.nodes.validate_route_node import (
    validate_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.state import (
    ToolRouteStateV1,
    ToolRoutingInputState,
    ToolRoutingParentOutputState,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRouteResultV1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    UserInterruptV1,
)

from .nodes.bind_registry_candidates_node import (
    bind_registry_candidates_node,
)
from .nodes.determine_io_resources_node import (
    determine_io_resources_node,
)
from .nodes.select_tool_if_needed_node import (
    select_tool_if_needed_node,
)
from .routing.route_after_bind_registry_candidates import (
    route_after_bind_registry_candidates,
)
from .routing.route_after_determine_io_resources import (
    route_after_determine_io_resources,
)
from .routing.route_after_finalize_route import (
    route_after_finalize_route,
)
from .routing.route_after_select_tool_if_needed import (
    route_after_select_tool_if_needed,
)
from .routing.route_after_validate_route import (
    route_after_validate_route,
)

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ToolRouteStateV1],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
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
    """Compile exactly the five canonical Tool Routing runtime nodes."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        tool_catalog: SignedToolRegistry,
        prompt_manifest_path: Path | None,
        graph_profile: GraphProfile,
        merge_decision: MergeDecision,
        confirm_inline: ConfirmInline,
        id_factory: Callable[[], str],
    ) -> None:
        self._llm_runtime = llm_runtime
        self._tool_catalog = tool_catalog
        manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._determine_prompt_ref = load_prompt_reference(
            "tool_routing.determine_io_resources", manifest_path
        )
        self._select_prompt_ref = load_prompt_reference(
            "tool_routing.select_tool_if_needed", manifest_path
        )
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._confirm_inline = confirm_inline
        self._id_factory = id_factory

    def build(self) -> Any:
        graph = StateGraph(
            ToolRouteStateV1,
            input_schema=ToolRoutingInputState,
            output_schema=ToolRoutingParentOutputState,
        )
        graph.add_node("determine_io_resources", self._determine_io_resources_node)
        graph.add_node("bind_registry_candidates", self._bind_registry_candidates_node)
        graph.add_node("select_tool_if_needed", self._select_tool_if_needed_node)
        graph.add_node("finalize_route", self._finalize_route_node)
        graph.add_node("validate_route", self._validate_route_node)
        graph.add_edge(START, "determine_io_resources")
        graph.add_conditional_edges(
            "determine_io_resources",
            route_after_determine_io_resources,
            {
                "finalize_route": "finalize_route",
                "bind_registry_candidates": "bind_registry_candidates",
            },
        )
        graph.add_conditional_edges(
            "bind_registry_candidates",
            route_after_bind_registry_candidates,
            {
                "finalize_route": "finalize_route",
                "select_tool_if_needed": "select_tool_if_needed",
            },
        )
        graph.add_conditional_edges(
            "select_tool_if_needed",
            route_after_select_tool_if_needed,
            {"finalize_route": "finalize_route"},
        )
        graph.add_conditional_edges(
            "finalize_route",
            route_after_finalize_route,
            {
                "determine_io_resources": "determine_io_resources",
                "bind_registry_candidates": "bind_registry_candidates",
                "validate_route": "validate_route",
            },
        )
        graph.add_conditional_edges("validate_route", route_after_validate_route, {"end": END})
        return graph.compile(name="tool_routing_subgraph")

    def _determine_io_resources_node(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        request = request_from_state(cast(Any, state))
        invocation_id = self._invocation_id(state)
        is_first_node = invocation_id is None
        if invocation_id is None:
            invocation_id = self._id_factory()
        initial_fields: ToolRouteStateV1 = {}
        if is_first_node:
            initial_fields = {
                "request_intent": _require_state_value(
                    state.get("request_intent"), "request_intent"
                ),
                "registry_snapshot_ref": self._tool_catalog.contract_version,
                "io_resource_candidate": None,
                "registry_candidates": [],
                "bound_input_routes": [],
                "bound_output_routes": [],
                "final_route": None,
            }
        working_state = cast(ToolRouteStateV1, {**state, **initial_fields})
        patch = determine_io_resources_node(
            working_state,
            llm_runtime=self._llm_runtime,
            tool_catalog=self._tool_catalog,
            prompt_ref=self._determine_prompt_ref,
        )
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_response", None)
        prompt_context.pop("confirmation_interrupt", None)
        result: ToolRouteStateV1 = {
            **initial_fields,
            **patch,
            "prompt_context": prompt_context,
            "trace_context": self._trace(
                working_state,
                node_name="determine_io_resources",
                llm_call_id=f"{request.run_id}:route.determine_resources",
                prompt_ref=self._determine_prompt_ref,
                llm_call_increment=1,
                invocation_id=invocation_id,
                agent_invocation_increment=1 if is_first_node else 0,
            ),
        }
        if result.get("io_resource_candidate") is None:
            result.update(self._confirmation_signal(cast(ToolRouteStateV1, {**state, **result})))
        return result

    def _bind_registry_candidates_node(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        patch = bind_registry_candidates_node(
            state, tool_catalog=self._tool_catalog, id_factory=self._id_factory
        )
        result: ToolRouteStateV1 = {
            **patch,
            "trace_context": self._trace(state, node_name="bind_registry_candidates"),
        }
        working_state = cast(ToolRouteStateV1, {**state, **patch})
        if working_state.get("workflow_signal") is not None:
            result.update(self._confirmation_signal(working_state))
            return result
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_response", None)
        prompt_context.pop("confirmation_interrupt", None)
        result.update({"user_interrupt": None, "prompt_context": prompt_context})
        return result

    def _select_tool_if_needed_node(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        candidates = state.get("registry_candidates", [])
        llm_call_count = sum(len(candidate.eligible_tool_ids) != 1 for candidate in candidates)
        request = request_from_state(cast(Any, state))
        return {
            **select_tool_if_needed_node(
                state,
                llm_runtime=self._llm_runtime,
                prompt_ref=self._select_prompt_ref,
            ),
            "trace_context": self._trace(
                state,
                node_name="select_tool_if_needed",
                llm_call_id=(f"{request.run_id}:route.select_tool" if llm_call_count else None),
                prompt_ref=(self._select_prompt_ref if llm_call_count else None),
                llm_call_increment=llm_call_count,
            ),
        }

    def _finalize_route_node(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        if state.get("user_interrupt") is not None:
            return self._resolve_confirmation(state)
        return {
            **finalize_route_node(
                state,
                tool_catalog=self._tool_catalog,
                id_factory=self._id_factory,
            ),
            "trace_context": self._trace(state, node_name="finalize_route"),
        }

    def _resolve_confirmation(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        raw_interrupt = cast(Mapping[str, object], state["user_interrupt"])
        interrupt_id = cast(str, raw_interrupt["interrupt_id"])
        is_scope_expansion = isinstance(raw_interrupt.get("policy_confirmation"), Mapping)
        confirmation_response, early_return_patch = self._confirm_inline(state)
        trace_context = self._trace(state, node_name="finalize_route")
        if early_return_patch is not None:
            return cast(
                ToolRouteStateV1,
                {**early_return_patch, "user_interrupt": None, "trace_context": trace_context},
            )
        if confirmation_response is None:
            raise ValueError("tool-routing confirmation response is required")
        origin = "scope_expansion" if is_scope_expansion else "semantic"
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context["confirmation_interrupt"] = {
            "semantic_owner_id": "TOOL_ROUTE",
            "origin_target": "tool_route.finalize",
            "origin": origin,
            "interrupt_id": interrupt_id,
        }
        if is_scope_expansion:
            prompt_context.pop("confirmation_response", None)
        else:
            prompt_context["confirmation_response"] = dict(confirmation_response)
        patch: ToolRouteStateV1 = {
            "user_interrupt": None,
            "prompt_context": prompt_context,
            "policy_confirmation_receipts": list(state.get("policy_confirmation_receipts", [])),
            "trace_context": trace_context,
        }
        if is_scope_expansion:
            patch["workflow_signal"] = None
        else:
            patch["io_resource_candidate"] = None
        return patch

    def _confirmation_signal(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        request_intent = _require_state_value(state.get("request_intent"), "request_intent")
        signal = state.get("workflow_signal")
        if isinstance(signal, Mapping) and signal.get("kind") == "SCOPE_EXPANSION_REQUIRED":
            typed_signal = cast(ScopeExpansionRequiredV1, signal)
            resources = ", ".join(typed_signal["required_resource_types"])
            question: request_understanding_output.ClarificationQuestionV1 = {
                "schema_version": 1,
                "origin_target": "tool_route.finalize",
                "question": (
                    f"This request requires additional read scope for {resources}. Proceed?"
                ),
                "affected_field_paths": ["requested_resource_hints"],
                "reason_code": (
                    typed_signal["reason_codes"][0]
                    if typed_signal["reason_codes"]
                    else "SCOPE_EXPANSION_REQUIRED"
                ),
                "known_context_summary": request_intent["goal"],
                "options": [
                    {
                        "option_id": "APPROVED",
                        "label": "네, 확인하고 진행합니다",
                    },
                    {
                        "option_id": "DECLINED",
                        "label": "아니요, 진행하지 않습니다",
                    },
                ],
            }
            origin = "scope_expansion"
        else:
            question = {
                "schema_version": 1,
                "origin_target": "tool_route.finalize",
                "question": "Please clarify the target resource or action type.",
                "affected_field_paths": [
                    "requested_resource_hints",
                    "requested_effect_hints",
                ],
                "reason_code": "TOOL_ROUTE_NEEDS_CONFIRMATION",
                "known_context_summary": request_intent["goal"],
                "options": [],
            }
            origin = "semantic"
        interrupt_id = self._id_factory()
        raw_interrupt: dict[str, object] = {
            **build_user_interrupt_v1(question),
            "interrupt_id": interrupt_id,
        }
        if origin == "scope_expansion":
            typed_signal = cast(ScopeExpansionRequiredV1, signal)
            raw_interrupt["policy_confirmation"] = {
                "confirmation_kind": "SCOPE_EXPANSION",
                "request_intent": request_intent,
                "required_resource_types": list(typed_signal["required_resource_types"]),
                "reason_codes": list(typed_signal["reason_codes"]),
                "affected_route_ids": _scope_expansion_affected_route_ids(
                    typed_signal["required_resource_types"]
                ),
            }
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context.pop("confirmation_response", None)
        prompt_context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "TOOL_ROUTE",
            "origin_target": "tool_route.finalize",
            "origin": origin,
        }
        return {
            "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
            "user_interrupt": cast(UserInterruptV1, raw_interrupt),
            "prompt_context": prompt_context,
        }

    def _validate_route_node(self, state: ToolRouteStateV1) -> ToolRouteStateV1:
        patch = validate_route_node(state, tool_catalog=self._tool_catalog)
        plan = patch.get("tool_route_plan")
        disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED", "BLOCKED"]
        if plan is None:
            disposition = "BLOCKED"
            reason_codes = [self._blocked_reason(state)]
        else:
            output_plan = plan["output_plan"]
            has_input = bool(plan["input_plan"]["input_routes"])
            disposition = (
                "NO_TOOL_NEEDED"
                if output_plan["output_mode"] == "ANSWER" and not has_input
                else "ROUTE_READY"
            )
            reason_codes = []
        result: ToolRouteResultV1 = {
            "schema_version": 1,
            "disposition": disposition,
            "tool_route_plan": plan,
            "workflow_signal": cast(ScopeExpansionRequiredV1 | None, patch["workflow_signal"]),
            "reason_codes": reason_codes,
        }
        decision = route_supervisor(
            phase=WorkflowPhase.TOOL_ROUTING,
            state=cast(MultiAgentGraphState, {**state, **patch}),
            result=result,
        )
        traced_state = {
            **state,
            **patch,
            "trace_context": self._trace(state, node_name="validate_route"),
        }
        return cast(
            ToolRouteStateV1,
            self._merge_decision(
                traced_state,
                {"workflow_phase": WorkflowPhase.TOOL_ROUTING.value},
                decision,
            ),
        )

    @staticmethod
    def _blocked_reason(state: ToolRouteStateV1) -> str:
        for receipt in reversed(state.get("policy_confirmation_receipts", [])):
            if receipt["decision"] == "DECLINED":
                return "SCOPE_EXPANSION_DECLINED"
        return "TOOL_ROUTE_BLOCKED"

    def _trace(
        self,
        state: ToolRouteStateV1,
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
            raise ValueError("tool-routing invocation id is required")
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="tool_route",
            agent_role="tool_routing",
            agent_invocation_id=resolved_invocation_id,
            subgraph_namespace="tool_routing",
            node_name=node_name,
            llm_call_id=llm_call_id,
            prompt_ref=prompt_ref,
            agent_invocation_increment=agent_invocation_increment,
            llm_call_increment=llm_call_increment,
        )

    @staticmethod
    def _invocation_id(state: ToolRouteStateV1) -> str | None:
        trace_context = state.get("trace_context", {})
        raw_log = trace_context.get("agent_node_log", [])
        if not isinstance(raw_log, list):
            return None
        for item in reversed(raw_log):
            if not isinstance(item, Mapping) or item.get("agent_subgraph_id") != "tool_route":
                continue
            invocation_id = item.get("agent_invocation_id")
            if isinstance(invocation_id, str) and invocation_id:
                return invocation_id
        return None


def build_tool_routing_subgraph(
    *,
    tool_catalog: SignedToolRegistry,
    llm_runtime: StructuredInferencePort,
    prompt_manifest_path: Path | None,
    id_factory: Callable[[], str],
    merge_decision: MergeDecision,
    graph_profile: GraphProfile,
    confirm_inline: ConfirmInline,
) -> Any:
    return ToolRoutingSubgraph(
        llm_runtime=llm_runtime,
        tool_catalog=tool_catalog,
        prompt_manifest_path=prompt_manifest_path,
        graph_profile=graph_profile,
        merge_decision=merge_decision,
        confirm_inline=confirm_inline,
        id_factory=id_factory,
    ).build()
