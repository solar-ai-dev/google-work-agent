"""Deterministic assembly of canonical Planning ActionPlanDraftV2.

LLM argument candidates contribute only business arguments/evidence references.
Frozen Tool Route contributes connector-independent route/tool/effect identity.
Dependency generation, normalization, cycle validation, and final typed-plan
assembly are deterministic code responsibilities.

The release runtime still carries ``ActionPlanDraftV1`` through Review/Domain
Validation.  ``assemble_action_plan_draft_v1_compat`` is a one-way compatibility
projection from the canonical V2 plan; it does not return any of the removed
legacy authoring authority to the LLM.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.planning_arguments import ToolArgumentCandidateV1
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)


class PlanningAssemblyError(ValueError):
    """Raised when Planning candidates cannot form one frozen canonical plan."""


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]


class ActionDependencyCandidateV1(TypedDict):
    action_id: str
    depends_on_action_id: str
    reason: str


class PlannedActionV2(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]
    depends_on_action_ids: list[str]


class ActionPlanDraftV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    actions: list[PlannedActionV2]


class PlanningActionSeedV1(TypedDict):
    action_id: str
    route_id: str
    tool_id: str
    effect: Literal["CREATE", "UPDATE", "SEND", "DELETE"]
    arguments: dict[str, object]
    evidence_refs: list[str]


_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})

# Only resources whose stable external identity is already present in approved
# business arguments are eligible for automatic dependency derivation. CREATE
# actions intentionally have no entry: their provider-generated resource id is
# not known before execution and must never be invented by Planning.
_TARGET_IDENTITY_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gmail_update_draft": ("GMAIL_DRAFT", ("draft_id",)),
    "gmail_send": ("GMAIL_DRAFT", ("draft_id",)),
    "tasks_update_task": ("TASK", ("task_list_id", "task_id")),
    "tasks_delete_task": ("TASK", ("task_list_id", "task_id")),
    "calendar_update_event": ("CALENDAR_EVENT", ("calendar_id", "event_id")),
    "calendar_delete_event": ("CALENDAR_EVENT", ("calendar_id", "event_id")),
}

_TARGET_RESOURCE_MATCH: dict[str, tuple[str, str]] = {
    "gmail_update_draft": ("draft_id", "gmail_draft:"),
    "tasks_update_task": ("task_id", "task:"),
    "tasks_delete_task": ("task_id", "task:"),
    "calendar_update_event": ("event_id", "calendar_event:"),
    "calendar_delete_event": ("event_id", "calendar_event:"),
}


def materialize_action_seeds(
    *,
    output_routes: Iterable[OutputToolRouteV1],
    argument_candidates: Iterable[ToolArgumentCandidateV1],
    action_id_factory: Callable[[], str],
    action_id_by_route: Mapping[str, str] | None = None,
) -> tuple[PlanningActionSeedV1, ...]:
    """Join exactly one argument candidate to each frozen output route."""

    routes = tuple(output_routes)
    candidates = tuple(argument_candidates)
    route_by_id = _unique_routes(routes)
    candidate_by_route = _unique_candidates(candidates)

    missing = set(route_by_id) - set(candidate_by_route)
    extra = set(candidate_by_route) - set(route_by_id)
    if missing or extra:
        raise PlanningAssemblyError(
            f"argument candidates must match frozen output routes; missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    if action_id_by_route is not None:
        extra_action_ids = set(action_id_by_route) - set(route_by_id)
        if extra_action_ids:
            raise PlanningAssemblyError(
                f"action id mapping references unknown routes: {sorted(extra_action_ids)}"
            )

    seeds: list[PlanningActionSeedV1] = []
    for route in routes:
        route_id = route["route_id"]
        candidate = candidate_by_route[route_id]
        effect = route["effect"]
        if effect not in _WRITE_EFFECTS:
            raise PlanningAssemblyError(f"output route is not a write effect: {route_id}")
        action_id = (
            action_id_by_route.get(route_id, "")
            if action_id_by_route is not None
            else action_id_factory()
        )
        if not action_id:
            raise PlanningAssemblyError("action id factory/mapping returned an empty id")
        seeds.append(
            {
                "action_id": action_id,
                "route_id": route_id,
                "tool_id": route["selected_tool_id"],
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
                "arguments": dict(candidate["arguments"]),
                "evidence_refs": list(candidate["evidence_refs"]),
            }
        )
    if len({seed["action_id"] for seed in seeds}) != len(seeds):
        raise PlanningAssemblyError("action id factory produced duplicate ids")
    return tuple(seeds)


def derive_action_dependencies_deterministically(
    action_seeds: Iterable[PlanningActionSeedV1],
) -> tuple[ActionDependencyCandidateV1, ...]:
    """Derive the minimal safe DAG from stable same-resource identities.

    Frozen route order is the only ordering input. Two actions are linked only
    when both target the same already-identifiable external resource. The
    later action depends on the immediately preceding action for that target;
    unrelated resources remain parallel. CREATE actions are deliberately not
    linked because their provider-generated id does not exist at plan time.
    """

    previous_action_by_target: dict[tuple[str, ...], str] = {}
    dependencies: list[ActionDependencyCandidateV1] = []
    for seed in action_seeds:
        target = _stable_target_identity(seed)
        if target is None:
            continue
        previous_action_id = previous_action_by_target.get(target)
        if previous_action_id is not None:
            dependencies.append(
                {
                    "action_id": seed["action_id"],
                    "depends_on_action_id": previous_action_id,
                    "reason": "SAME_RESOURCE_ORDER",
                }
            )
        previous_action_by_target[target] = seed["action_id"]
    return tuple(dependencies)


def assemble_action_plan_draft_v2(
    *,
    artifact_id: str,
    revision: int,
    based_on: Iterable[StateArtifactRefV1],
    action_seeds: Iterable[PlanningActionSeedV1],
    dependency_candidates: Iterable[ActionDependencyCandidateV1] | None = None,
) -> ActionPlanDraftV2:
    """Derive/validate dependencies and assemble the immutable Planning artifact."""

    if not artifact_id:
        raise PlanningAssemblyError("artifact_id must not be empty")
    if revision < 1:
        raise PlanningAssemblyError("revision must be at least 1")
    seeds = tuple(action_seeds)
    if not seeds:
        raise PlanningAssemblyError("action plan requires at least one action")
    action_ids = [seed["action_id"] for seed in seeds]
    if len(set(action_ids)) != len(action_ids):
        raise PlanningAssemblyError("duplicate action_id in action seeds")

    dependencies = (
        derive_action_dependencies_deterministically(seeds)
        if dependency_candidates is None
        else tuple(dependency_candidates)
    )
    dependencies_by_action: dict[str, list[str]] = {action_id: [] for action_id in action_ids}
    seen_edges: set[tuple[str, str]] = set()
    for candidate in dependencies:
        action_id = candidate["action_id"]
        dependency_id = candidate["depends_on_action_id"]
        if action_id not in dependencies_by_action or dependency_id not in dependencies_by_action:
            raise PlanningAssemblyError("dependency references an action outside this plan")
        if action_id == dependency_id:
            raise PlanningAssemblyError("action cannot depend on itself")
        edge = (action_id, dependency_id)
        if edge in seen_edges:
            continue
        seen_edges.add(edge)
        dependencies_by_action[action_id].append(dependency_id)

    _validate_acyclic(dependencies_by_action)
    actions: list[PlannedActionV2] = [
        {
            "action_id": seed["action_id"],
            "route_id": seed["route_id"],
            "tool_id": seed["tool_id"],
            "effect": seed["effect"],
            "arguments": dict(seed["arguments"]),
            "evidence_refs": list(seed["evidence_refs"]),
            "depends_on_action_ids": list(dependencies_by_action[seed["action_id"]]),
        }
        for seed in seeds
    ]
    return {
        "schema_version": 2,
        "meta": {
            "artifact_id": artifact_id,
            "revision": revision,
            "based_on": [dict(ref) for ref in based_on],  # type: ignore[list-item]
        },
        "actions": actions,
    }


def assemble_action_plan_draft_v1_compat(
    *,
    request_intent: RequestIntentV2,
    analysis_result: WorkAnalysisResultV1,
    evidence_drafts: list[EvidenceDraftV1],
    output_routes: tuple[OutputToolRouteV1, ...],
    argument_candidates: tuple[ToolArgumentCandidateV1, ...],
    plan_id_factory: Callable[[], str],
    action_id_factory: Callable[[], str],
    revision: int = 1,
    previous_plan: ActionPlanDraftV1 | None = None,
) -> ActionPlanDraftV1:
    """Project canonical per-route Planning output into the legacy review shape.

    Tool/effect/action identity, dependency and Expected are code-owned here.
    LLM candidates contribute only validated business arguments and evidence
    references.  Revision preserves the previous plan/action ids after exact
    frozen-route alignment so Review references cannot be silently retargeted.
    """

    plan_id = previous_plan["plan_id"] if previous_plan is not None else plan_id_factory()
    if not plan_id:
        raise PlanningAssemblyError("plan id must not be empty")
    action_id_by_route = _previous_action_ids_by_route(
        output_routes=output_routes,
        previous_plan=previous_plan,
    )
    seeds = materialize_action_seeds(
        output_routes=output_routes,
        argument_candidates=argument_candidates,
        action_id_factory=action_id_factory,
        action_id_by_route=action_id_by_route,
    )
    intent_meta = request_intent["meta"]
    canonical = assemble_action_plan_draft_v2(
        artifact_id=plan_id,
        revision=revision,
        based_on=[
            {
                "artifact_id": intent_meta["artifact_id"],
                "revision": intent_meta["revision"],
            }
        ],
        action_seeds=seeds,
    )

    evidence_by_id = {draft["evidence_id"]: draft for draft in evidence_drafts}
    resource_refs_by_handle = {
        str(ref["resource_handle"]): dict(ref)
        for ref in analysis_result["resource_refs"]
        if isinstance(ref.get("resource_handle"), str)
    }
    plan_evidence_refs = _stable_unique(
        evidence_ref for action in canonical["actions"] for evidence_ref in action["evidence_refs"]
    )
    plan_resource_handles = _stable_unique(
        evidence_by_id[evidence_ref]["resource_handle"]
        for evidence_ref in plan_evidence_refs
        if evidence_ref in evidence_by_id
        and evidence_by_id[evidence_ref]["resource_handle"] in resource_refs_by_handle
    )
    plan_resource_refs = [resource_refs_by_handle[handle] for handle in plan_resource_handles]

    legacy_actions: list[dict[str, object]] = []
    for position, action in enumerate(canonical["actions"], start=1):
        action_resource_handles = _stable_unique(
            evidence_by_id[evidence_ref]["resource_handle"]
            for evidence_ref in action["evidence_refs"]
            if evidence_ref in evidence_by_id
            and evidence_by_id[evidence_ref]["resource_handle"] in resource_refs_by_handle
        )
        target_resource_ref_id = _target_resource_handle(
            tool_id=action["tool_id"],
            arguments=action["arguments"],
            resource_refs_by_handle=resource_refs_by_handle,
        )
        legacy_actions.append(
            {
                "schema_version": 2,
                "action_id": action["action_id"],
                "position": position,
                "effect": action["effect"],
                "tool_name": action["tool_id"],
                "arguments": dict(action["arguments"]),
                "expected": build_expected_verification_projection(
                    tool_name=action["tool_id"],
                    arguments=action["arguments"],
                ),
                "evidence_refs": list(action["evidence_refs"]),
                "resource_refs": action_resource_handles,
                "target_resource_ref_id": target_resource_ref_id,
                "depends_on_action_ids": list(action["depends_on_action_ids"]),
                "user_visible_reason": request_intent["goal"],
            }
        )

    return cast(
        ActionPlanDraftV1,
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": plan_id,
            "summary": analysis_result["summary"] or request_intent["goal"],
            "objective": request_intent["goal"],
            "actions": legacy_actions,
            "evidence_refs": plan_evidence_refs,
            "resource_refs": plan_resource_refs,
            "confirmation": None,
        },
    )


def _previous_action_ids_by_route(
    *,
    output_routes: tuple[OutputToolRouteV1, ...],
    previous_plan: ActionPlanDraftV1 | None,
) -> dict[str, str] | None:
    if previous_plan is None:
        return None
    write_actions = [action for action in previous_plan["actions"] if action["effect"] != "READ"]
    if len(write_actions) != len(output_routes):
        raise PlanningAssemblyError(
            "previous plan does not have exactly one write action per frozen output route"
        )
    result: dict[str, str] = {}
    for route, action in zip(output_routes, write_actions, strict=True):
        if action["tool_name"] != route["selected_tool_id"] or action["effect"] != route["effect"]:
            raise PlanningAssemblyError(
                f"previous action does not align with frozen output route: {route['route_id']}"
            )
        result[route["route_id"]] = action["action_id"]
    return result


def _target_resource_handle(
    *,
    tool_id: str,
    arguments: Mapping[str, object],
    resource_refs_by_handle: Mapping[str, dict[str, object]],
) -> str | None:
    match = _TARGET_RESOURCE_MATCH.get(tool_id)
    if match is None:
        return None
    argument_name, handle_prefix = match
    target_id = arguments.get(argument_name)
    if not isinstance(target_id, str) or not target_id:
        return None
    matches = [
        handle
        for handle, resource_ref in resource_refs_by_handle.items()
        if handle.startswith(handle_prefix) and resource_ref.get("resource_id") == target_id
    ]
    if len(matches) > 1:
        raise PlanningAssemblyError(
            f"multiple resource refs match selected Tool target: {tool_id}/{target_id}"
        )
    return matches[0] if matches else None


def _stable_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _stable_target_identity(seed: PlanningActionSeedV1) -> tuple[str, ...] | None:
    identity_spec = _TARGET_IDENTITY_FIELDS.get(seed["tool_id"])
    if identity_spec is None:
        return None
    resource_type, fields = identity_spec
    values: list[str] = [resource_type]
    for field in fields:
        value = seed["arguments"].get(field)
        if not isinstance(value, str) or not value.strip():
            raise PlanningAssemblyError(
                f"stable target identity is missing {field}: {seed['tool_id']}"
            )
        values.append(value.strip())
    return tuple(values)


def _unique_routes(routes: tuple[OutputToolRouteV1, ...]) -> dict[str, OutputToolRouteV1]:
    result: dict[str, OutputToolRouteV1] = {}
    for route in routes:
        route_id = route["route_id"]
        if route_id in result:
            raise PlanningAssemblyError(f"duplicate frozen output route: {route_id}")
        result[route_id] = route
    if not result:
        raise PlanningAssemblyError("ACTION planning requires frozen output routes")
    return result


def _unique_candidates(
    candidates: tuple[ToolArgumentCandidateV1, ...],
) -> dict[str, ToolArgumentCandidateV1]:
    result: dict[str, ToolArgumentCandidateV1] = {}
    for candidate in candidates:
        route_id = candidate["route_id"]
        if route_id in result:
            raise PlanningAssemblyError(f"duplicate argument candidate: {route_id}")
        result[route_id] = candidate
    return result


def _validate_acyclic(dependencies: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(action_id: str) -> None:
        if action_id in visited:
            return
        if action_id in visiting:
            raise PlanningAssemblyError("action dependency cycle detected")
        visiting.add(action_id)
        for dependency_id in dependencies[action_id]:
            visit(dependency_id)
        visiting.remove(action_id)
        visited.add(action_id)

    for action_id in dependencies:
        visit(action_id)


__all__ = [
    "ActionDependencyCandidateV1",
    "ActionPlanDraftV2",
    "PlannedActionV2",
    "PlanningActionSeedV1",
    "PlanningAssemblyError",
    "StateArtifactMetaV1",
    "StateArtifactRefV1",
    "assemble_action_plan_draft_v1_compat",
    "assemble_action_plan_draft_v2",
    "derive_action_dependencies_deterministically",
    "materialize_action_seeds",
]
