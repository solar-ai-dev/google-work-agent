from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import cast

from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import RouteBindingCandidateV1
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import SemanticRouteCandidate
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import InputToolRouteV1, OutputToolRouteV1, ToolRouteEffect
from google_work_agent.application.agents.tool_routing.validate_route import ToolRouteValidationError
from google_work_agent.domain import ConnectorToolCatalog, EffectType

ToolSelector = Callable[..., str]
SelectedToolMap = Mapping[tuple[str, str], str]


def normalize_resource_type(value: str) -> str:
    normalized = value.strip().upper()
    return {"GMAIL": "GMAIL_THREAD", "EMAIL": "GMAIL_THREAD", "TASKS": "TASK", "CALENDAR": "CALENDAR_EVENT", "EVENT": "CALENDAR_EVENT"}.get(normalized, normalized)


def coarse_resource_category(resource_type: str) -> str:
    if resource_type.startswith("GMAIL"):
        return "EMAIL"
    if resource_type in {"TASK", "TASK_LIST"}:
        return "TASK"
    if resource_type.startswith("CALENDAR"):
        return "CALENDAR"
    raise ToolRouteValidationError(f"resource type has no coarse category: {resource_type}")


def registry_candidates_for_route(*, tool_catalog: ConnectorToolCatalog, resource_type: str, effect_type: EffectType) -> tuple[str, tuple[str, ...]]:
    """Return the bounded Registry candidates for one semantic output route."""
    return _eligible_bindings(tool_catalog, resource_type, effect_type)


def bind_registry_candidates(*, candidate: SemanticRouteCandidate, tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str], select_tool: ToolSelector | None = None, selected_tools: SelectedToolMap | None = None) -> RouteBindingCandidateV1:
    output_routes: list[OutputToolRouteV1] = []
    for resource_type, effect_type in candidate.output_pairs:
        connector_id, candidates = registry_candidates_for_route(tool_catalog=tool_catalog, resource_type=resource_type, effect_type=effect_type)
        route_id = id_factory()
        selected = selected_tools.get((resource_type, effect_type.value)) if selected_tools is not None else None
        if selected is not None:
            if selected not in candidates:
                raise ToolRouteValidationError(f"selected tool is not a registered candidate: {resource_type}/{effect_type.value}")
            selected_tool_id = selected
            reason_codes = ["LLM_SELECTED_FROM_REGISTRY_CANDIDATES"]
        elif len(candidates) == 1:
            selected_tool_id = candidates[0]
            reason_codes = ["REGISTRY_SINGLE_CANDIDATE"]
        elif select_tool is not None:
            selected_tool_id = select_tool(route_id=route_id, connector_id=connector_id, resource_type=resource_type, effect=effect_type.value, eligible_tool_ids=candidates)
            if selected_tool_id not in candidates:
                raise ToolRouteValidationError(f"selected tool is not a registered candidate: {resource_type}/{effect_type.value}")
            reason_codes = ["LLM_SELECTED_FROM_REGISTRY_CANDIDATES"]
        else:
            raise ToolRouteValidationError(f"route binding requires exactly one registered tool: {resource_type}/{effect_type.value}")
        output_routes.append({"route_id": route_id, "resource_type": resource_type, "connector_id": connector_id, "effect": cast(ToolRouteEffect, effect_type.value), "selected_tool_id": selected_tool_id, "reason_codes": reason_codes})
    input_routes = _bind_input_routes(resource_types=candidate.input_resource_types, tool_catalog=tool_catalog, id_factory=id_factory, reason_code="REQUESTED_INPUT")
    existing = {route["resource_type"] for route in input_routes}
    for resource_type, reason_code in _read_dependencies(candidate.input_resource_types):
        if resource_type in existing:
            continue
        input_routes.extend(_bind_input_routes(resource_types=(resource_type,), tool_catalog=tool_catalog, id_factory=id_factory, reason_code=reason_code))
        existing.add(resource_type)
    return RouteBindingCandidateV1(semantic=candidate, input_routes=tuple(input_routes), output_routes=tuple(output_routes))


def _bind_input_routes(*, resource_types: Iterable[str], tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str], reason_code: str) -> list[InputToolRouteV1]:
    routes: list[InputToolRouteV1] = []
    for resource_type in sorted(set(resource_types)):
        connector_id, candidates = _eligible_bindings(tool_catalog, resource_type, EffectType.READ)
        routes.append({"route_id": id_factory(), "resource_type": resource_type, "connector_id": connector_id, "allowed_read_tool_ids": list(candidates), "required": True, "reason_codes": [reason_code]})
    return routes


def _eligible_bindings(tool_catalog: ConnectorToolCatalog, resource_type: str, effect_type: EffectType) -> tuple[str, tuple[str, ...]]:
    matches: list[tuple[str, tuple[str, ...]]] = []
    for connector_id in tool_catalog.list_connector_ids():
        entries = tool_catalog.eligible(connector_id=connector_id, resource_type=resource_type, effect_type=effect_type)
        if entries:
            matches.append((connector_id, tuple(entry.tool_name for entry in entries)))
    if len(matches) != 1:
        raise ToolRouteValidationError(f"resource/effect must resolve to exactly one connector: {resource_type}/{effect_type.value}")
    return matches[0]


def _read_dependencies(resource_types: Iterable[str]) -> tuple[tuple[str, str], ...]:
    dependencies = {"GMAIL_THREAD": (("GMAIL_MESSAGE", "RETRIEVAL_THREAD_MESSAGE_DETAIL"),), "GMAIL_MESSAGE": (("GMAIL_THREAD", "RETRIEVAL_GMAIL_DISCOVERY"),), "TASK": (("TASK_LIST", "RETRIEVAL_TASK_LIST_DISCOVERY"),), "TASK_LIST": (("TASK", "RETRIEVAL_TASK_DETAIL"),), "CALENDAR": (("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DETAIL"),), "CALENDAR_EVENT": (("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"), ("CALENDAR_FREEBUSY", "RETRIEVAL_CALENDAR_FREEBUSY_AVAILABILITY")), "CALENDAR_FREEBUSY": (("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"), ("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DISCOVERY"))}
    return tuple(dependency for resource_type in sorted(set(resource_types)) if resource_type in dependencies for dependency in dependencies[resource_type])
