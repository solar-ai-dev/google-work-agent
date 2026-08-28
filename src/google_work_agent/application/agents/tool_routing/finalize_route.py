from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.tool_routing.contracts.route_binding_candidate import (
    RouteBindingCandidateV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputRoutePlanV1,
    InputToolRouteV1,
    OutputPlanV1,
    OutputToolRouteV1,
    ToolRoutePlanV2,
    ToolRouteResultV1,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
    validate_route,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry

SelectedToolMap = Mapping[tuple[str, str], str]


def finalize_route(
    *,
    request_intent: RequestIntentV2,
    binding: RouteBindingCandidateV1,
    selected_tools: SelectedToolMap,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
    previous_plan: ToolRoutePlanV2 | None = None,
) -> ToolRouteResultV1:
    try:
        request_ref = _request_intent_ref(request_intent)
        input_routes = [dict(route) for route in binding.input_routes]
        output_routes = _materialize_output_routes(binding=binding, selected_tools=selected_tools)
        plan = _freeze_plan(
            request_ref=request_ref,
            input_routes=input_routes,
            output_routes=output_routes,
            output_mode=binding.semantic.output_mode,
            previous_plan=previous_plan,
            tool_catalog=tool_catalog,
            id_factory=id_factory,
        )
        validate_route(plan, tool_catalog=tool_catalog)
    except (LookupError, ToolRouteValidationError, ValueError) as error:
        return _result("BLOCKED", None, [str(error)], None)
    disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED"] = (
        "NO_TOOL_NEEDED"
        if not input_routes and binding.semantic.output_mode == "ANSWER"
        else "ROUTE_READY"
    )
    return _result(disposition, plan, [], None)


def _materialize_output_routes(
    *, binding: RouteBindingCandidateV1, selected_tools: SelectedToolMap
) -> list[OutputToolRouteV1]:
    output_routes: list[OutputToolRouteV1] = []
    for bound in binding.output_candidates:
        key = (bound.resource_type, bound.effect)
        selected_tool_id = selected_tools.get(key)
        if selected_tool_id is None:
            raise ToolRouteValidationError(
                "tool selection is required after Registry binding: "
                f"{bound.resource_type}/{bound.effect}"
            )
        if selected_tool_id not in bound.eligible_tool_ids:
            raise ToolRouteValidationError(
                "selected tool is outside the bound eligible set: "
                f"{bound.resource_type}/{bound.effect}"
            )
        reason_codes = (
            ["REGISTRY_SINGLE_CANDIDATE"]
            if len(bound.eligible_tool_ids) == 1
            else ["LLM_SELECTED_FROM_BOUND_REGISTRY_CANDIDATES"]
        )
        output_routes.append(
            {
                "route_id": bound.route_id,
                "resource_type": bound.resource_type,
                "connector_id": bound.connector_id,
                "effect": bound.effect,
                "selected_tool_id": selected_tool_id,
                "reason_codes": reason_codes,
            }
        )
    return output_routes


def _freeze_plan(
    *,
    request_ref: StateArtifactRefV1,
    input_routes: list[InputToolRouteV1],
    output_routes: list[OutputToolRouteV1],
    output_mode: Literal["ANSWER", "ACTION"],
    previous_plan: ToolRoutePlanV2 | None,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
) -> ToolRoutePlanV2:
    input_revision = (
        1 if previous_plan is None else previous_plan["input_plan"]["meta"]["revision"] + 1
    )
    output_revision = (
        1 if previous_plan is None else previous_plan["output_plan"]["meta"]["revision"] + 1
    )
    input_plan: InputRoutePlanV1 = {
        "schema_version": 1,
        "meta": {
            "artifact_id": id_factory(),
            "revision": input_revision,
            "based_on": [request_ref],
        },
        "input_routes": input_routes,
    }
    if output_mode == "ANSWER":
        output_plan: OutputPlanV1 = {
            "schema_version": 1,
            "meta": {
                "artifact_id": id_factory(),
                "revision": output_revision,
                "based_on": [request_ref],
            },
            "output_mode": "ANSWER",
        }
    else:
        output_plan = {
            "schema_version": 1,
            "meta": {
                "artifact_id": id_factory(),
                "revision": output_revision,
                "based_on": [request_ref],
            },
            "output_mode": "ACTION",
            "output_routes": output_routes,
        }
    if not tool_catalog.entries:
        raise ToolRouteValidationError("active Tool Registry must not be empty")
    return {
        "schema_version": 2,
        "input_plan": input_plan,
        "output_plan": output_plan,
        "tool_registry_version": tool_catalog.contract_version,
    }


def _request_intent_ref(request_intent: RequestIntentV2) -> StateArtifactRefV1:
    meta = request_intent.get("meta")
    if not isinstance(meta, Mapping):
        raise ToolRouteValidationError("RequestIntentV2.meta is required")
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id or not isinstance(revision, int):
        raise ToolRouteValidationError("RequestIntentV2.meta is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _result(
    disposition: Literal["ROUTE_READY", "NO_TOOL_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"],
    plan: ToolRoutePlanV2 | None,
    reason_codes: list[str],
    signal: None,
) -> ToolRouteResultV1:
    return {
        "schema_version": 1,
        "disposition": disposition,
        "tool_route_plan": plan,
        "workflow_signal": signal,
        "reason_codes": reason_codes,
    }
