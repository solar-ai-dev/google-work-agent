"""Canonical Tool Route V2 contracts and deterministic route ownership.

The Tool Route semantic LLM stage (PromptRef, LLM invocation, semantic
candidate/tool-selection validation) lives in ``tool_route_semantic.py``.
This module owns everything downstream of a ``SemanticRouteCandidate``:
deterministic Registry binding, PolicyPreconditionResolver, validation,
revision, and freezing into a ``ToolRoutePlanV2``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import (
    RequestIntentV2,
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.domain import ConnectorToolCatalog, EffectType

ToolRouteEffect = Literal["CREATE", "UPDATE", "SEND", "DELETE"]
ToolSelector = Callable[..., str]


class InputToolRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    allowed_read_tool_ids: list[str]
    required: bool
    reason_codes: list[str]


class OutputToolRouteV1(TypedDict):
    route_id: str
    resource_type: str
    connector_id: str
    effect: ToolRouteEffect
    selected_tool_id: str
    reason_codes: list[str]


class InputRoutePlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    input_routes: list[InputToolRouteV1]


class AnswerOutputPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    output_mode: Required[Literal["ANSWER"]]


class ActionOutputPlanV1(TypedDict):
    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    output_mode: Required[Literal["ACTION"]]
    output_routes: list[OutputToolRouteV1]


OutputPlanV1 = AnswerOutputPlanV1 | ActionOutputPlanV1


class ToolRoutePlanV2(TypedDict):
    schema_version: Required[Literal[2]]
    input_plan: InputRoutePlanV1
    output_plan: OutputPlanV1
    tool_registry_version: str


class RouteReconsiderationRequiredV1(TypedDict):
    schema_version: Required[Literal[1]]
    kind: Required[Literal["ROUTE_RECONSIDERATION_REQUIRED"]]
    reason_codes: list[str]


class ScopeExpansionRequiredV1(TypedDict):
    schema_version: Required[Literal[1]]
    kind: Required[Literal["SCOPE_EXPANSION_REQUIRED"]]
    reason_codes: list[str]
    required_resource_types: list[str]


class ToolRouteDisposition(StrEnum):
    ROUTE_READY = "ROUTE_READY"
    NO_TOOL_NEEDED = "NO_TOOL_NEEDED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    BLOCKED = "BLOCKED"


class ToolRouteResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    disposition: str
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: ScopeExpansionRequiredV1 | None
    reason_codes: list[str]


class ToolRouteValidationError(ValueError):
    """Raised when a frozen Tool Route violates its Registry contract."""


@dataclass(frozen=True, slots=True)
class SemanticRouteCandidate:
    input_resource_types: tuple[str, ...]
    output_pairs: tuple[tuple[str, EffectType], ...]
    output_mode: Literal["ANSWER", "ACTION"]
    analysis_requirement: Literal["NONE", "REQUIRED"]


class PolicyPreconditionResolver:
    """Add mandatory policy reads without selecting another output tool."""

    def required_reads(
        self,
        output_routes: Iterable[OutputToolRouteV1],
    ) -> tuple[tuple[str, str, str], ...]:
        required: set[tuple[str, str, str]] = set()
        for route in output_routes:
            key = (route["resource_type"], route["effect"])
            if key == ("TASK", "CREATE"):
                required.update(
                    {
                        (route["connector_id"], "TASK", "POLICY_TASK_DUPLICATE_CHECK"),
                        (route["connector_id"], "TASK_LIST", "POLICY_TASK_DUPLICATE_CHECK"),
                    }
                )
            elif key == ("CALENDAR_EVENT", "CREATE"):
                required.update(
                    {
                        (
                            route["connector_id"],
                            "CALENDAR",
                            "POLICY_CALENDAR_CONFLICT_CHECK",
                        ),
                        (
                            route["connector_id"],
                            "CALENDAR_EVENT",
                            "POLICY_CALENDAR_CONFLICT_CHECK",
                        ),
                        (
                            route["connector_id"],
                            "CALENDAR_FREEBUSY",
                            "POLICY_CALENDAR_CONFLICT_CHECK",
                        ),
                    }
                )
        return tuple(sorted(required))


class ReadDependencyResolver:
    """Describe provider-neutral read capabilities required by one input route."""

    def required_reads(
        self,
        resource_types: Iterable[str],
    ) -> tuple[tuple[str, str], ...]:
        dependencies = {
            "GMAIL_THREAD": (("GMAIL_MESSAGE", "RETRIEVAL_THREAD_MESSAGE_DETAIL"),),
            "GMAIL_MESSAGE": (("GMAIL_THREAD", "RETRIEVAL_GMAIL_DISCOVERY"),),
            "TASK": (("TASK_LIST", "RETRIEVAL_TASK_LIST_DISCOVERY"),),
            "TASK_LIST": (("TASK", "RETRIEVAL_TASK_DETAIL"),),
            "CALENDAR": (("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DETAIL"),),
            "CALENDAR_EVENT": (
                ("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"),
                ("CALENDAR_FREEBUSY", "RETRIEVAL_CALENDAR_FREEBUSY_AVAILABILITY"),
            ),
            "CALENDAR_FREEBUSY": (
                ("CALENDAR", "RETRIEVAL_CALENDAR_DISCOVERY"),
                ("CALENDAR_EVENT", "RETRIEVAL_CALENDAR_EVENT_DISCOVERY"),
            ),
        }
        return tuple(
            dependency
            for resource_type in sorted(set(resource_types))
            if resource_type in dependencies
            for dependency in dependencies[resource_type]
        )


class ToolRouteCoordinator:
    """Own semantic routing, Registry binding, policy enrichment, and freezing."""

    def __init__(
        self,
        *,
        tool_catalog: ConnectorToolCatalog,
        id_factory: Callable[[], str],
        policy_preconditions: PolicyPreconditionResolver | None = None,
        read_dependencies: ReadDependencyResolver | None = None,
    ) -> None:
        self._tool_catalog = tool_catalog
        self._id_factory = id_factory
        self._policy_preconditions = policy_preconditions or PolicyPreconditionResolver()
        self._read_dependencies = read_dependencies or ReadDependencyResolver()

    def route(
        self,
        *,
        request_intent: RequestIntentV2,
        previous_plan: ToolRoutePlanV2 | None = None,
        semantic_candidate: SemanticRouteCandidate | None = None,
        semantic_candidate_provider: Callable[[], SemanticRouteCandidate] | None = None,
        select_tool: ToolSelector | None = None,
    ) -> ToolRouteResultV1:
        """Bind a frozen ``ToolRoutePlanV2`` from a semantic route candidate.

        ``semantic_candidate``/``semantic_candidate_provider`` are the release
        path: the Tool Route LLM stage (``ToolRouteAgent.determine_semantic_candidate``)
        owns semantic resource/effect selection there. When neither is given,
        ``determine_semantic_routes`` is used instead -- a deterministic
        compatibility path kept for callers (tests, non-LLM invocations) that
        supply ``request_intent`` hints directly. Exactly one candidate source
        ever runs per call; they are not alternate opinions reconciled against
        each other.
        """

        if semantic_candidate is not None:
            candidate = semantic_candidate
        else:
            provider = semantic_candidate_provider or (
                lambda: determine_semantic_routes(request_intent)
            )
            try:
                candidate = provider()
            except ToolRouteValidationError as error:
                return _route_result(
                    disposition=ToolRouteDisposition.NEEDS_CONFIRMATION,
                    plan=None,
                    reason_codes=[str(error)],
                )

        request_ref = _request_intent_ref(request_intent)
        try:
            output_routes = self._bind_output_routes(
                candidate.output_pairs, select_tool=select_tool
            )
            input_routes = self._bind_input_routes(
                candidate.input_resource_types,
                reason_code="REQUESTED_INPUT",
            )
            input_routes = self._merge_read_dependencies(
                input_routes=input_routes,
                requested_resource_types=candidate.input_resource_types,
            )
            input_routes = self._merge_policy_preconditions(
                input_routes=input_routes,
                output_routes=output_routes,
            )
            plan = self._freeze_plan(
                request_ref=request_ref,
                input_routes=input_routes,
                output_routes=output_routes,
                output_mode=candidate.output_mode,
                previous_plan=previous_plan,
            )
            validate_tool_route_plan_v2(plan, tool_catalog=self._tool_catalog)
        except (LookupError, ToolRouteValidationError, ValueError) as error:
            return _route_result(
                disposition=ToolRouteDisposition.BLOCKED,
                plan=None,
                reason_codes=[str(error)],
            )
        disposition = (
            ToolRouteDisposition.NO_TOOL_NEEDED
            if not input_routes and candidate.output_mode == "ANSWER"
            else ToolRouteDisposition.ROUTE_READY
        )
        return _route_result(disposition=disposition, plan=plan, reason_codes=[])

    def _bind_output_routes(
        self,
        output_pairs: tuple[tuple[str, EffectType], ...],
        *,
        select_tool: ToolSelector | None = None,
    ) -> list[OutputToolRouteV1]:
        routes: list[OutputToolRouteV1] = []
        for resource_type, effect_type in output_pairs:
            connector_id, candidates = self._eligible_bindings(
                resource_type=resource_type,
                effect_type=effect_type,
            )
            route_id = self._id_factory()
            if len(candidates) == 1:
                selected_tool_id = candidates[0]
                reason_codes = ["REGISTRY_SINGLE_CANDIDATE"]
            elif select_tool is not None:
                selected_tool_id = select_tool(
                    route_id=route_id,
                    connector_id=connector_id,
                    resource_type=resource_type,
                    effect=effect_type.value,
                    eligible_tool_ids=candidates,
                )
                if selected_tool_id not in candidates:
                    raise ToolRouteValidationError(
                        f"selected tool is not a registered candidate: "
                        f"{resource_type}/{effect_type.value}"
                    )
                reason_codes = ["LLM_SELECTED_FROM_REGISTRY_CANDIDATES"]
            else:
                raise ToolRouteValidationError(
                    f"route binding requires exactly one registered tool: "
                    f"{resource_type}/{effect_type.value}"
                )
            routes.append(
                {
                    "route_id": route_id,
                    "resource_type": resource_type,
                    "connector_id": connector_id,
                    "effect": cast(ToolRouteEffect, effect_type.value),
                    "selected_tool_id": selected_tool_id,
                    "reason_codes": reason_codes,
                }
            )
        return routes

    def _merge_read_dependencies(
        self,
        *,
        input_routes: list[InputToolRouteV1],
        requested_resource_types: Iterable[str],
    ) -> list[InputToolRouteV1]:
        existing = {route["resource_type"] for route in input_routes}
        for resource_type, reason_code in self._read_dependencies.required_reads(
            requested_resource_types
        ):
            if resource_type in existing:
                continue
            input_routes.extend(
                self._bind_input_routes((resource_type,), reason_code=reason_code)
            )
            existing.add(resource_type)
        return input_routes

    def _bind_input_routes(
        self,
        resource_types: Iterable[str],
        *,
        reason_code: str,
    ) -> list[InputToolRouteV1]:
        routes: list[InputToolRouteV1] = []
        for resource_type in sorted(set(resource_types)):
            connector_id, candidates = self._eligible_bindings(
                resource_type=resource_type,
                effect_type=EffectType.READ,
            )
            if not candidates:
                raise ToolRouteValidationError(f"no registered read tool: {resource_type}")
            routes.append(
                {
                    "route_id": self._id_factory(),
                    "resource_type": resource_type,
                    "connector_id": connector_id,
                    "allowed_read_tool_ids": list(candidates),
                    "required": True,
                    "reason_codes": [reason_code],
                }
            )
        return routes

    def _merge_policy_preconditions(
        self,
        *,
        input_routes: list[InputToolRouteV1],
        output_routes: list[OutputToolRouteV1],
    ) -> list[InputToolRouteV1]:
        by_key = {
            (route["connector_id"], route["resource_type"]): route for route in input_routes
        }
        for connector_id, resource_type, reason_code in self._policy_preconditions.required_reads(
            output_routes
        ):
            key = (connector_id, resource_type)
            existing = by_key.get(key)
            if existing is not None:
                if reason_code not in existing["reason_codes"]:
                    existing["reason_codes"].append(reason_code)
                continue
            candidates = self._tool_catalog.eligible(
                connector_id=connector_id,
                resource_type=resource_type,
                effect_type=EffectType.READ,
            )
            if not candidates:
                raise ToolRouteValidationError(
                    f"policy precondition read is not registered: {resource_type}"
                )
            route: InputToolRouteV1 = {
                "route_id": self._id_factory(),
                "resource_type": resource_type,
                "connector_id": connector_id,
                "allowed_read_tool_ids": [entry.tool_name for entry in candidates],
                "required": True,
                "reason_codes": [reason_code],
            }
            by_key[key] = route
        return sorted(by_key.values(), key=lambda route: route["route_id"])

    def _eligible_bindings(
        self,
        *,
        resource_type: str,
        effect_type: EffectType,
    ) -> tuple[str, tuple[str, ...]]:
        matches: list[tuple[str, tuple[str, ...]]] = []
        for connector_id in self._tool_catalog.list_connector_ids():
            entries = self._tool_catalog.eligible(
                connector_id=connector_id,
                resource_type=resource_type,
                effect_type=effect_type,
            )
            if entries:
                matches.append((connector_id, tuple(entry.tool_name for entry in entries)))
        if len(matches) != 1:
            raise ToolRouteValidationError(
                f"resource/effect must resolve to exactly one connector: "
                f"{resource_type}/{effect_type.value}"
            )
        return matches[0]

    def _freeze_plan(
        self,
        *,
        request_ref: StateArtifactRefV1,
        input_routes: list[InputToolRouteV1],
        output_routes: list[OutputToolRouteV1],
        output_mode: Literal["ANSWER", "ACTION"],
        previous_plan: ToolRoutePlanV2 | None,
    ) -> ToolRoutePlanV2:
        input_revision = _next_revision(previous_plan, "input_plan")
        output_revision = _next_revision(previous_plan, "output_plan")
        input_plan: InputRoutePlanV1 = {
            "schema_version": 1,
            "meta": _meta(self._id_factory(), input_revision, request_ref),
            "input_routes": input_routes,
        }
        if output_mode == "ANSWER":
            output_plan: OutputPlanV1 = {
                "schema_version": 1,
                "meta": _meta(self._id_factory(), output_revision, request_ref),
                "output_mode": "ANSWER",
            }
        else:
            output_plan = {
                "schema_version": 1,
                "meta": _meta(self._id_factory(), output_revision, request_ref),
                "output_mode": "ACTION",
                "output_routes": output_routes,
            }
        versions = {
            self._tool_catalog.registry_for(connector_id).list_entries()[0].registry_version
            for connector_id in self._tool_catalog.list_connector_ids()
            if self._tool_catalog.registry_for(connector_id).list_entries()
        }
        if len(versions) != 1:
            raise ToolRouteValidationError("active connector registries must share one version")
        return {
            "schema_version": 2,
            "input_plan": input_plan,
            "output_plan": output_plan,
            "tool_registry_version": next(iter(versions)),
        }


_WRITE_EFFECTS = frozenset(
    {EffectType.CREATE, EffectType.UPDATE, EffectType.SEND, EffectType.DELETE}
)


def determine_semantic_routes(request_intent: RequestIntentV2) -> SemanticRouteCandidate:
    """Project request meaning without reading Registry tool identities.

    Deterministic compatibility path (tests, non-LLM invocations) --
    ``ToolRouteAgent.determine_semantic_candidate`` owns this in the release
    path (Q3). RequestIntentV2 has no ``response_disposition`` field:
    ACTION vs ANSWER is inferred from whether ``requested_effect_hints``
    contains a write effect, matching ``ToolRouteEffect``/Tool Route's own
    output-route vocabulary (READ is never a valid output effect there).
    RequestIntentV2 also has no ``semantic_constraints.sources`` fallback;
    ``requested_resource_hints`` is the sole resource-hint field Tool Route
    reads. ``constraints`` (including ``kind == "RESOURCE"``, which per the
    PHASE 7.5 candidate schema carries ``selected_resource_ids`` -- specific
    resource identifiers, not a resource-type/source hint) is general
    request-understanding structure with no documented Tool Route routing
    role (06-agent-workflow.md SS3.1/SS5.3); it is intentionally not
    consulted here.
    """

    resource_hints = tuple(
        dict.fromkeys(
            normalize_resource_type(item)
            for item in request_intent.get("requested_resource_hints", [])
        )
    )
    effect_hints = tuple(
        EffectType(item) for item in request_intent.get("requested_effect_hints", [])
    )
    write_effect_hints = tuple(effect for effect in effect_hints if effect in _WRITE_EFFECTS)
    output_mode: Literal["ANSWER", "ACTION"] = "ACTION" if write_effect_hints else "ANSWER"
    if output_mode == "ACTION":
        if not resource_hints:
            raise ToolRouteValidationError("ACTION route requires resource and effect hints")
        if len(write_effect_hints) == 1:
            output_pairs = tuple((resource, write_effect_hints[0]) for resource in resource_hints)
        elif len(write_effect_hints) == len(resource_hints):
            output_pairs = tuple(zip(resource_hints, write_effect_hints, strict=True))
        else:
            raise ToolRouteValidationError("resource/effect hint cardinality is ambiguous")
        input_resources = resource_hints
    else:
        output_pairs = ()
        input_resources = resource_hints
    analysis_requirement = cast(
        Literal["NONE", "REQUIRED"],
        request_intent.get("analysis_requirement", "REQUIRED"),
    )
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise ToolRouteValidationError("analysis_requirement is invalid")
    return SemanticRouteCandidate(
        input_resource_types=input_resources,
        output_pairs=output_pairs,
        output_mode=output_mode,
        analysis_requirement=analysis_requirement,
    )


def validate_tool_route_plan_v2(
    value: object,
    *,
    tool_catalog: ConnectorToolCatalog,
) -> ToolRoutePlanV2:
    root = _mapping(value, "$")
    if set(root) != {"schema_version", "input_plan", "output_plan", "tool_registry_version"}:
        raise ToolRouteValidationError("ToolRoutePlanV2 fields are invalid")
    if root["schema_version"] != 2:
        raise ToolRouteValidationError("ToolRoutePlanV2.schema_version must be 2")
    registry_version = _string(root, "tool_registry_version")
    input_plan = _mapping(root["input_plan"], "$.input_plan")
    output_plan = _mapping(root["output_plan"], "$.output_plan")
    _validate_plan_meta(input_plan, "$.input_plan")
    _validate_plan_meta(output_plan, "$.output_plan")
    input_routes = input_plan.get("input_routes")
    if not isinstance(input_routes, list):
        raise ToolRouteValidationError("$.input_plan.input_routes must be a list")
    route_ids: set[str] = set()
    for index, raw_route in enumerate(input_routes):
        route = _mapping(raw_route, f"$.input_plan.input_routes[{index}]")
        if set(route) != {
            "route_id",
            "resource_type",
            "connector_id",
            "allowed_read_tool_ids",
            "required",
            "reason_codes",
        }:
            raise ToolRouteValidationError("input route fields are invalid")
        _validate_route_id(route, route_ids)
        connector_id = _string(route, "connector_id")
        resource_type = _string(route, "resource_type")
        tool_ids = route.get("allowed_read_tool_ids")
        if not isinstance(tool_ids, list) or not tool_ids:
            raise ToolRouteValidationError("input route requires allowed_read_tool_ids")
        if not isinstance(route.get("required"), bool):
            raise ToolRouteValidationError("input route required must be boolean")
        _validate_reason_codes(route)
        for tool_id in tool_ids:
            if not isinstance(tool_id, str):
                raise ToolRouteValidationError("allowed_read_tool_ids must contain strings")
            entry = tool_catalog.require(connector_id=connector_id, tool_id=tool_id)
            if entry.effect_type is not EffectType.READ or entry.resource_type != resource_type:
                raise ToolRouteValidationError("input route tool binding is invalid")
            if entry.registry_version != registry_version:
                raise ToolRouteValidationError("input route registry version is stale")
    output_mode = output_plan.get("output_mode")
    if output_mode == "ANSWER":
        if "output_routes" in output_plan:
            raise ToolRouteValidationError("ANSWER output must not contain output_routes")
    elif output_mode == "ACTION":
        output_routes = output_plan.get("output_routes")
        if not isinstance(output_routes, list) or not output_routes:
            raise ToolRouteValidationError("ACTION output requires output_routes")
        for raw_route in output_routes:
            route = _mapping(raw_route, "$.output_plan.output_routes[]")
            if set(route) != {
                "route_id",
                "resource_type",
                "connector_id",
                "effect",
                "selected_tool_id",
                "reason_codes",
            }:
                raise ToolRouteValidationError("output route fields are invalid")
            _validate_route_id(route, route_ids)
            _validate_reason_codes(route)
            connector_id = _string(route, "connector_id")
            resource_type = _string(route, "resource_type")
            tool_id = _string(route, "selected_tool_id")
            try:
                effect = EffectType(_string(route, "effect"))
            except ValueError as error:
                raise ToolRouteValidationError("output route effect is invalid") from error
            if effect is EffectType.READ:
                raise ToolRouteValidationError("output route effect must be a write effect")
            entry = tool_catalog.require(connector_id=connector_id, tool_id=tool_id)
            if entry.effect_type is not effect or entry.resource_type != resource_type:
                raise ToolRouteValidationError("output route tool binding is invalid")
            if entry.registry_version != registry_version:
                raise ToolRouteValidationError("output route registry version is stale")
    else:
        raise ToolRouteValidationError("output_mode is invalid")
    return cast(ToolRoutePlanV2, value)


def allowed_input_sources(plan: ToolRoutePlanV2) -> frozenset[str]:
    return frozenset(
        _resource_source(route["resource_type"])
        for route in plan["input_plan"]["input_routes"]
    )


def allowed_read_tool_ids(plan: ToolRoutePlanV2, *, source: str) -> frozenset[str]:
    return frozenset(
        tool_id
        for route in plan["input_plan"]["input_routes"]
        if _resource_source(route["resource_type"]) == source
        for tool_id in route["allowed_read_tool_ids"]
    )


def output_routes(plan: ToolRoutePlanV2) -> tuple[OutputToolRouteV1, ...]:
    output_plan = plan["output_plan"]
    if output_plan["output_mode"] == "ANSWER":
        return ()
    return tuple(output_plan["output_routes"])


def _request_intent_ref(request_intent: RequestIntentV2) -> StateArtifactRefV1:
    raw_meta = request_intent.get("meta")
    if not isinstance(raw_meta, Mapping):
        raise ToolRouteValidationError("RequestIntentV2.meta is required")
    artifact_id = raw_meta.get("artifact_id")
    revision = raw_meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id or not isinstance(revision, int):
        raise ToolRouteValidationError("RequestIntentV2.meta is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _route_result(
    *,
    disposition: ToolRouteDisposition,
    plan: ToolRoutePlanV2 | None,
    reason_codes: list[str],
) -> ToolRouteResultV1:
    return {
        "schema_version": 1,
        "disposition": disposition.value,
        "tool_route_plan": plan,
        "workflow_signal": None,
        "reason_codes": reason_codes,
    }


def normalize_resource_type(value: str) -> str:
    """Expand a coarse or aliased resource type to its canonical form.

    Shared by ``determine_semantic_routes`` (deterministic compatibility
    path) and ``tool_route_semantic._semantic_candidate_from_llm_candidate``
    (LLM release path) -- both need the same coarse-to-canonical mapping,
    e.g. the LLM's "EMAIL"/"CALENDAR" -> "GMAIL_THREAD"/"CALENDAR_EVENT".
    """

    normalized = value.strip().upper()
    aliases = {
        "GMAIL": "GMAIL_THREAD",
        "EMAIL": "GMAIL_THREAD",
        "TASKS": "TASK",
        "CALENDAR": "CALENDAR_EVENT",
        "EVENT": "CALENDAR_EVENT",
    }
    return aliases.get(normalized, normalized)


def _resource_source(resource_type: str) -> str:
    if resource_type.startswith("GMAIL_"):
        return "GMAIL"
    if resource_type in {"TASK", "TASK_LIST"}:
        return "TASKS"
    if resource_type.startswith("CALENDAR"):
        return "CALENDAR"
    raise ToolRouteValidationError(f"resource type has no source projection: {resource_type}")


def coarse_resource_category(resource_type: str) -> str:
    """Collapse a canonical resource type to the Prompt-facing EMAIL/TASK/CALENDAR category.

    The inverse of ``normalize_resource_type``. Shared by the Tool Route
    semantic LLM stage (``tool_route_semantic.py``) and Retrieval's
    ``retrieval.plan_query`` input projection (``api_acquisition.py``):
    both must render Registry/Route-level resource types (e.g.
    "GMAIL_THREAD", "TASK_LIST", "CALENDAR_FREEBUSY") into the same
    3-value enum every PHASE 7.5 Prompt schema uses for resource_type.
    """

    if resource_type.startswith("GMAIL"):
        return "EMAIL"
    if resource_type in {"TASK", "TASK_LIST"}:
        return "TASK"
    if resource_type.startswith("CALENDAR"):
        return "CALENDAR"
    raise ToolRouteValidationError(f"resource type has no coarse category: {resource_type}")


def _next_revision(plan: ToolRoutePlanV2 | None, key: Literal["input_plan", "output_plan"]) -> int:
    return 1 if plan is None else plan[key]["meta"]["revision"] + 1


def _meta(artifact_id: str, revision: int, based_on: StateArtifactRefV1) -> StateArtifactMetaV1:
    return {"artifact_id": artifact_id, "revision": revision, "based_on": [based_on]}


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolRouteValidationError(f"{path} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ToolRouteValidationError(f"{key} must be a non-empty string")
    return item


def _validate_plan_meta(value: Mapping[str, object], path: str) -> None:
    if value.get("schema_version") != 1:
        raise ToolRouteValidationError(f"{path}.schema_version must be 1")
    meta = _mapping(value.get("meta"), f"{path}.meta")
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise ToolRouteValidationError(f"{path}.meta fields are invalid")
    if (
        not isinstance(meta.get("artifact_id"), str)
        or not meta["artifact_id"]
        or not isinstance(meta.get("revision"), int)
        or cast(int, meta["revision"]) < 1
    ):
        raise ToolRouteValidationError(f"{path}.meta is invalid")
    based_on = meta.get("based_on")
    if not isinstance(based_on, list) or not based_on:
        raise ToolRouteValidationError(f"{path}.meta.based_on is required")
    for reference in based_on:
        item = _mapping(reference, f"{path}.meta.based_on[]")
        if set(item) != {"artifact_id", "revision"}:
            raise ToolRouteValidationError(f"{path}.meta.based_on fields are invalid")
        if not isinstance(item.get("artifact_id"), str) or not isinstance(
            item.get("revision"), int
        ):
            raise ToolRouteValidationError(f"{path}.meta.based_on is invalid")


def _validate_route_id(route: Mapping[str, object], route_ids: set[str]) -> None:
    route_id = _string(route, "route_id")
    if route_id in route_ids:
        raise ToolRouteValidationError(f"duplicate route_id: {route_id}")
    route_ids.add(route_id)


def _validate_reason_codes(route: Mapping[str, object]) -> None:
    reason_codes = route.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ToolRouteValidationError("route reason_codes must contain strings")
