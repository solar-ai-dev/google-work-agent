from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from google_work_agent.application.agents.request_understanding.contracts.request_intent import RequestIntentV2, StateArtifactRefV1
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import coarse_resource_category
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import RouteBindingCandidateV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import InputRoutePlanV1, InputToolRouteV1, OutputPlanV1, OutputToolRouteV1, ScopeExpansionRequiredV1, ToolRoutePlanV2, ToolRouteResultV1
from google_work_agent.application.agents.tool_routing.validate_route import ToolRouteValidationError, validate_route
from google_work_agent.application.orchestration.contracts import PolicyConfirmationReceiptV1
from google_work_agent.application.orchestration.scope_expansion import ScopeExpansionResolver
from google_work_agent.domain import ConnectorToolCatalog, EffectType

SelectedToolMap = Mapping[tuple[str, str], str]


def finalize_route(*, request_intent: RequestIntentV2, binding: RouteBindingCandidateV1, selected_tools: SelectedToolMap, tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str], previous_plan: ToolRoutePlanV2 | None = None, policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1] = (), current_interrupt_id: str | None = None, scope_expansion: ScopeExpansionResolver | None = None) -> ToolRouteResultV1:
    try:
        request_ref = _request_intent_ref(request_intent)
        input_routes = [dict(route) for route in binding.input_routes]
        output_routes = _materialize_output_routes(binding=binding, selected_tools=selected_tools)
        required_reads = _policy_precondition_reads(output_routes)
        resolver = scope_expansion or ScopeExpansionResolver()
        out_of_scope = resolver.out_of_scope_reads(request_intent=request_intent, required_reads=required_reads, category_of=coarse_resource_category)
        if out_of_scope:
            required_resource_types = tuple(sorted({read[1] for read in out_of_scope}))
            reason_codes = tuple(sorted({read[2] for read in out_of_scope}))
            approval = resolver.find_valid_approval(request_intent=request_intent, required_resource_types=required_resource_types, reason_codes=reason_codes, receipts=policy_confirmation_receipts, current_interrupt_id=current_interrupt_id)
            if approval is None:
                signal: ScopeExpansionRequiredV1 = {"schema_version": 1, "kind": "SCOPE_EXPANSION_REQUIRED", "reason_codes": list(reason_codes), "required_resource_types": list(required_resource_types)}
                return _result("NEEDS_CONFIRMATION", None, ["SCOPE_EXPANSION_REQUIRED"], signal)
        input_routes = _merge_policy_reads(input_routes=input_routes, required_reads=required_reads, tool_catalog=tool_catalog, id_factory=id_factory)
        plan = _freeze_plan(request_ref=request_ref, input_routes=input_routes, output_routes=output_routes, output_mode=binding.semantic.output_mode, previous_plan=previous_plan, tool_catalog=tool_catalog, id_factory=id_factory)
        validate_route(plan, tool_catalog=tool_catalog)
    except (LookupError, ToolRouteValidationError, ValueError) as error:
        return _result("BLOCKED", None, [str(error)], None)
    disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED"] = "NO_TOOL_NEEDED" if not input_routes and binding.semantic.output_mode == "ANSWER" else "ROUTE_READY"
    return _result(disposition, plan, [], None)


def _materialize_output_routes(*, binding: RouteBindingCandidateV1, selected_tools: SelectedToolMap) -> list[OutputToolRouteV1]:
    output_routes: list[OutputToolRouteV1] = []
    for bound in binding.output_candidates:
        key = (bound.resource_type, bound.effect)
        selected_tool_id = selected_tools.get(key)
        if selected_tool_id is None:
            raise ToolRouteValidationError(f"tool selection is required after Registry binding: {bound.resource_type}/{bound.effect}")
        if selected_tool_id not in bound.eligible_tool_ids:
            raise ToolRouteValidationError(f"selected tool is outside the bound eligible set: {bound.resource_type}/{bound.effect}")
        reason_codes = ["REGISTRY_SINGLE_CANDIDATE"] if len(bound.eligible_tool_ids) == 1 else ["LLM_SELECTED_FROM_BOUND_REGISTRY_CANDIDATES"]
        output_routes.append({"route_id": bound.route_id, "resource_type": bound.resource_type, "connector_id": bound.connector_id, "effect": bound.effect, "selected_tool_id": selected_tool_id, "reason_codes": reason_codes})
    return output_routes


def _policy_precondition_reads(output_routes: list[OutputToolRouteV1]) -> tuple[tuple[str, str, str], ...]:
    required: set[tuple[str, str, str]] = set()
    for route in output_routes:
        key = (route["resource_type"], route["effect"])
        if key == ("TASK", "CREATE"):
            required.update({(route["connector_id"], "TASK", "POLICY_TASK_DUPLICATE_CHECK"), (route["connector_id"], "TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK")})
        elif key == ("CALENDAR_EVENT", "CREATE"):
            required.update({(route["connector_id"], "CALENDAR", "POLICY_CALENDAR_CONFLICT_CHECK"), (route["connector_id"], "CALENDAR_EVENT", "POLICY_CALENDAR_CONFLICT_CHECK"), (route["connector_id"], "CALENDAR_FREEBUSY", "POLICY_CALENDAR_CONFLICT_CHECK")})
    return tuple(sorted(required))


def _merge_policy_reads(*, input_routes: list[InputToolRouteV1], required_reads: tuple[tuple[str, str, str], ...], tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str]) -> list[InputToolRouteV1]:
    by_key = {(route["connector_id"], route["resource_type"]): route for route in input_routes}
    for connector_id, resource_type, reason_code in required_reads:
        key = (connector_id, resource_type)
        existing = by_key.get(key)
        if existing is not None:
            if reason_code not in existing["reason_codes"]:
                existing["reason_codes"].append(reason_code)
            continue
        candidates = tool_catalog.eligible(connector_id=connector_id, resource_type=resource_type, effect_type=EffectType.READ)
        if not candidates:
            raise ToolRouteValidationError(f"policy precondition read is not registered: {resource_type}")
        by_key[key] = {"route_id": id_factory(), "resource_type": resource_type, "connector_id": connector_id, "allowed_read_tool_ids": [entry.tool_name for entry in candidates], "required": True, "reason_codes": [reason_code]}
    return sorted(by_key.values(), key=lambda route: route["route_id"])


def _freeze_plan(*, request_ref: StateArtifactRefV1, input_routes: list[InputToolRouteV1], output_routes: list[OutputToolRouteV1], output_mode: Literal["ANSWER", "ACTION"], previous_plan: ToolRoutePlanV2 | None, tool_catalog: ConnectorToolCatalog, id_factory: Callable[[], str]) -> ToolRoutePlanV2:
    input_revision = 1 if previous_plan is None else previous_plan["input_plan"]["meta"]["revision"] + 1
    output_revision = 1 if previous_plan is None else previous_plan["output_plan"]["meta"]["revision"] + 1
    input_plan: InputRoutePlanV1 = {"schema_version": 1, "meta": {"artifact_id": id_factory(), "revision": input_revision, "based_on": [request_ref]}, "input_routes": input_routes}
    if output_mode == "ANSWER":
        output_plan: OutputPlanV1 = {"schema_version": 1, "meta": {"artifact_id": id_factory(), "revision": output_revision, "based_on": [request_ref]}, "output_mode": "ANSWER"}
    else:
        output_plan = {"schema_version": 1, "meta": {"artifact_id": id_factory(), "revision": output_revision, "based_on": [request_ref]}, "output_mode": "ACTION", "output_routes": output_routes}
    versions = {tool_catalog.registry_for(connector_id).list_entries()[0].registry_version for connector_id in tool_catalog.list_connector_ids() if tool_catalog.registry_for(connector_id).list_entries()}
    if len(versions) != 1:
        raise ToolRouteValidationError("active connector registries must share one version")
    return {"schema_version": 2, "input_plan": input_plan, "output_plan": output_plan, "tool_registry_version": next(iter(versions))}


def _request_intent_ref(request_intent: RequestIntentV2) -> StateArtifactRefV1:
    meta = request_intent.get("meta")
    if not isinstance(meta, Mapping):
        raise ToolRouteValidationError("RequestIntentV2.meta is required")
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id or not isinstance(revision, int):
        raise ToolRouteValidationError("RequestIntentV2.meta is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _result(disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"], plan: ToolRoutePlanV2 | None, reason_codes: list[str], signal: ScopeExpansionRequiredV1 | None) -> ToolRouteResultV1:
    return {"schema_version": 1, "disposition": disposition, "tool_route_plan": plan, "workflow_signal": signal, "reason_codes": reason_codes}
