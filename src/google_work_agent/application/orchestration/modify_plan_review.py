"""Deterministic approval-time MODIFY_REVIEW reconstruction for Runtime V2.

The durable store may contribute only the user's current business arguments and
current dependency rows. Frozen Tool Route and the current ActionPlanDraftV2
remain the semantic identity authority; persisted Expected values are never
read into the reconstructed V2 artifact.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from json import loads
from typing import Literal, cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    RetrievalResultV1,
    StateArtifactRefV1,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
    PlanningActionSeedV1,
    PlanningAssemblyError,
    assemble_action_plan_draft_v2,
)
from google_work_agent.application.orchestration.state_artifacts import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus


class ModifyReviewV2Error(ValueError):
    """The durable/current snapshots cannot authorize a V2 modify review."""


@dataclass(frozen=True, slots=True)
class ModifyReviewDurableSnapshot:
    """Bounded durable facts needed to reconstruct one modified plan revision."""

    plan: PlanRecord
    actions: tuple[ActionRecord, ...]
    dependencies_by_action: Mapping[str, Sequence[str]]


def reconstruct_modified_action_plan_v2(
    *,
    run_id: str,
    plan_id: str,
    review_version: int,
    current_plan: ActionPlanDraftV2,
    tool_route_plan: ToolRoutePlanV2,
    work_analysis_result: WorkAnalysisResultV2,
    retrieval_result: RetrievalResultV1,
    durable: ModifyReviewDurableSnapshot,
) -> ActionPlanDraftV2:
    """Rebuild one V2 plan from frozen identity plus allowed durable edits.

    Identity/effect/evidence remain exactly the current V2 plan. Only current
    persisted ``arguments_json`` and dependency rows are admitted from durable
    state. ``expected_json`` and persisted risk are deliberately ignored.
    """

    _validate_plan_gate(
        run_id=run_id,
        plan_id=plan_id,
        review_version=review_version,
        current_plan=current_plan,
        durable_plan=durable.plan,
    )
    routes = _frozen_output_routes(tool_route_plan)
    current_actions = current_plan.get("actions")
    if not isinstance(current_actions, list) or not current_actions:
        raise ModifyReviewV2Error("current ActionPlanDraftV2 has no actions")
    if len(current_actions) != len(routes):
        raise ModifyReviewV2Error("current V2 actions do not align with frozen output routes")

    persisted_actions = sorted(durable.actions, key=lambda item: item.position)
    expected_positions = list(range(1, len(current_actions) + 1))
    if [item.position for item in persisted_actions] != expected_positions:
        raise ModifyReviewV2Error(
            "persisted action positions are not a complete deterministic order"
        )
    if len(persisted_actions) != len(current_actions):
        raise ModifyReviewV2Error("persisted action count does not match current V2 plan")

    current_ids = [action.get("action_id") for action in current_actions]
    persisted_ids = [action.id for action in persisted_actions]
    if any(not isinstance(item, str) or not item for item in current_ids):
        raise ModifyReviewV2Error("current V2 plan contains an invalid action id")
    action_ids = cast(list[str], current_ids)
    if len(set(action_ids)) != len(action_ids):
        raise ModifyReviewV2Error("current V2 plan contains duplicate action ids")
    if persisted_ids != action_ids:
        raise ModifyReviewV2Error("persisted action order/identity is stale")

    seeds: list[PlanningActionSeedV1] = []
    for index, (current, route, persisted) in enumerate(
        zip(current_actions, routes, persisted_actions, strict=True), start=1
    ):
        route_id = _required_text(route.get("route_id"), f"output route {index} id")
        selected_tool_id = _required_text(
            route.get("selected_tool_id"), f"output route {index} selected_tool_id"
        )
        connector_id = _required_text(
            route.get("connector_id"), f"output route {index} connector_id"
        )
        effect = route.get("effect")
        if effect not in {"CREATE", "UPDATE", "SEND", "DELETE"}:
            raise ModifyReviewV2Error(f"output route {index} is not a write effect")
        if current.get("route_id") != route_id:
            raise ModifyReviewV2Error(f"current action route is stale at position {index}")
        if current.get("tool_id") != selected_tool_id:
            raise ModifyReviewV2Error(f"current action tool is stale at position {index}")
        if current.get("effect") != effect:
            raise ModifyReviewV2Error(f"current action effect is stale at position {index}")
        if persisted.plan_id != plan_id or persisted.id != current.get("action_id"):
            raise ModifyReviewV2Error(f"persisted action identity is stale at position {index}")
        if persisted.tool_name != selected_tool_id or persisted.effect_type != effect:
            raise ModifyReviewV2Error(
                f"persisted action semantic identity is stale at position {index}"
            )
        if persisted.connector_id != connector_id:
            raise ModifyReviewV2Error(f"persisted action connector is stale at position {index}")

        try:
            arguments = loads(persisted.arguments_json)
        except (TypeError, ValueError) as exc:
            raise ModifyReviewV2Error(
                f"persisted action arguments are invalid JSON at position {index}"
            ) from exc
        if not isinstance(arguments, dict):
            raise ModifyReviewV2Error(
                f"persisted action arguments must be an object at position {index}"
            )
        evidence_refs = current.get("evidence_refs")
        if not isinstance(evidence_refs, list) or any(
            not isinstance(item, str) or not item for item in evidence_refs
        ):
            raise ModifyReviewV2Error(
                f"current action evidence refs are invalid at position {index}"
            )
        seeds.append(
            {
                "action_id": cast(str, current["action_id"]),
                "route_id": route_id,
                "tool_id": selected_tool_id,
                "effect": cast(Literal["CREATE", "UPDATE", "SEND", "DELETE"], effect),
                "arguments": cast(dict[str, object], arguments),
                "evidence_refs": list(cast(list[str], evidence_refs)),
            }
        )

    dependency_candidates: list[ActionDependencyCandidateV1] = []
    known_ids = set(action_ids)
    extra_dependency_owners = set(durable.dependencies_by_action) - known_ids
    if extra_dependency_owners:
        raise ModifyReviewV2Error(
            f"dependency rows reference unknown owning actions: {sorted(extra_dependency_owners)}"
        )
    for action_id in action_ids:
        raw_dependencies = durable.dependencies_by_action.get(action_id, ())
        for dependency_id in raw_dependencies:
            if not isinstance(dependency_id, str) or not dependency_id:
                raise ModifyReviewV2Error("dependency id must be a non-empty string")
            dependency_candidates.append(
                {
                    "action_id": action_id,
                    "depends_on_action_id": dependency_id,
                    "reason": "DURABLE_MODIFY_REVIEW",
                }
            )

    current_meta = current_plan.get("meta")
    if not isinstance(current_meta, Mapping):
        raise ModifyReviewV2Error("current ActionPlanDraftV2 meta is missing")
    artifact_id = _required_text(current_meta.get("artifact_id"), "current plan artifact id")
    revision = current_meta.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ModifyReviewV2Error("current plan revision is invalid")
    based_on = _ordered_unique_refs(
        (
            _artifact_ref(current_meta, "previous ActionPlanDraftV2"),
            _artifact_ref(_output_plan_meta(tool_route_plan), "Tool Route output plan"),
            _artifact_ref(work_analysis_result.get("meta"), "WorkAnalysisResultV2"),
            _artifact_ref(retrieval_result.get("meta"), "RetrievalResultV1"),
        )
    )
    try:
        return assemble_action_plan_draft_v2(
            artifact_id=artifact_id,
            revision=revision + 1,
            based_on=based_on,
            action_seeds=seeds,
            dependency_candidates=dependency_candidates,
        )
    except PlanningAssemblyError as exc:
        raise ModifyReviewV2Error(str(exc)) from exc


def durable_review_status_for_v2(review: PlanReviewResultV2) -> PlanReviewStatus | None:
    """Map only durable statuses that migration 0004 can represent.

    ROUTE_RECONSIDERATION intentionally has no downgrade. Callers must first
    reconcile/supersede the durable WAITING_APPROVAL generation before routing
    back to Tool Route.
    """

    return {
        "PASS": PlanReviewStatus.PASSED,
        "REVISE": PlanReviewStatus.REVISE,
        "RETRIEVE_MORE": PlanReviewStatus.RETRIEVE_MORE,
        "CONFIRM": PlanReviewStatus.REQUIRED,
        "BLOCK": PlanReviewStatus.BLOCKED,
        "ROUTE_RECONSIDERATION": None,
    }[review["status"]]


def _validate_plan_gate(
    *,
    run_id: str,
    plan_id: str,
    review_version: int,
    current_plan: ActionPlanDraftV2,
    durable_plan: PlanRecord,
) -> None:
    if not run_id or not plan_id or review_version < 0:
        raise ModifyReviewV2Error("modify review identity is invalid")
    if durable_plan.id != plan_id or durable_plan.run_id != run_id:
        raise ModifyReviewV2Error("persisted PlanRecord does not belong to this run/review")
    if durable_plan.review_status is not PlanReviewStatus.REQUIRED:
        raise ModifyReviewV2Error("persisted PlanRecord is not awaiting modify review")
    if durable_plan.review_version != review_version:
        raise ModifyReviewV2Error("persisted PlanRecord review version is stale")
    meta = current_plan.get("meta")
    if not isinstance(meta, Mapping) or meta.get("artifact_id") != plan_id:
        raise ModifyReviewV2Error("current V2 plan artifact does not match persisted plan_id")


def _frozen_output_routes(tool_route_plan: ToolRoutePlanV2) -> list[Mapping[str, object]]:
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping) or output_plan.get("output_mode") != "ACTION":
        raise ModifyReviewV2Error("modify review requires frozen ACTION output plan")
    routes = output_plan.get("output_routes")
    if not isinstance(routes, list) or not routes:
        raise ModifyReviewV2Error("modify review requires frozen output routes")
    if any(not isinstance(route, Mapping) for route in routes):
        raise ModifyReviewV2Error("frozen output route is invalid")
    return cast(list[Mapping[str, object]], routes)


def _output_plan_meta(tool_route_plan: ToolRoutePlanV2) -> object:
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping):
        raise ModifyReviewV2Error("Tool Route output plan is missing")
    return output_plan.get("meta")


def _artifact_ref(value: object, label: str) -> StateArtifactRefV1:
    if not isinstance(value, Mapping):
        raise ModifyReviewV2Error(f"{label} meta is missing")
    artifact_id = _required_text(value.get("artifact_id"), f"{label} artifact id")
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ModifyReviewV2Error(f"{label} revision is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _ordered_unique_refs(values: Sequence[StateArtifactRefV1]) -> list[StateArtifactRefV1]:
    result: list[StateArtifactRefV1] = []
    seen: set[tuple[str, int]] = set()
    for value in values:
        key = (value["artifact_id"], value["revision"])
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ModifyReviewV2Error(f"{label} is required")
    return value


__all__ = [
    "ModifyReviewDurableSnapshot",
    "ModifyReviewV2Error",
    "durable_review_status_for_v2",
    "reconstruct_modified_action_plan_v2",
]
