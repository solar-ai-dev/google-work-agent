"""Post-approval V2 replan identity rollover contract.

Normal pre-approval Review.REVISE keeps the same ActionPlanDraftV2 artifact and
action ids.  This module owns the distinct post-approval identity boundary:
once a durable approved plan has been superseded, the next official V2 plan
must use a fresh plan id and fresh action ids before Review/Domain Validation.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import (
    RetrievalResultV1,
    StateArtifactRefV1,
)
from google_work_agent.application.workflows.planning_plan_assembler import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
    PlanningActionSeedV1,
    PlanningAssemblyError,
    assemble_action_plan_draft_v2,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2, output_routes

PostApprovalReplanTriggerV1 = Literal["REVISE", "RETRIEVE_MORE"]
PostApprovalReplanPhaseV1 = Literal["ROLLOVER_REQUIRED", "IDENTITY_PREALLOCATED"]


class PostApprovalReplanIdentityV1(TypedDict):
    schema_version: Required[Literal[1]]
    source_plan_id: str
    source_action_ids: list[str]
    trigger: PostApprovalReplanTriggerV1
    phase: PostApprovalReplanPhaseV1
    preallocated_plan_id: str | None
    preallocated_action_ids: list[str]


class PostApprovalReplanV2Error(ValueError):
    """Post-approval identity rollover cannot be proven safely."""


def begin_post_approval_replan_identity(
    *,
    source_plan: ActionPlanDraftV2,
    trigger: PostApprovalReplanTriggerV1,
) -> PostApprovalReplanIdentityV1:
    """Capture the superseded generation before any fresh Planning result exists."""

    source_plan_id, source_action_ids = _plan_identity(source_plan)
    return {
        "schema_version": 1,
        "source_plan_id": source_plan_id,
        "source_action_ids": source_action_ids,
        "trigger": trigger,
        "phase": "ROLLOVER_REQUIRED",
        "preallocated_plan_id": None,
        "preallocated_action_ids": [],
    }


def validate_post_approval_replan_identity(
    value: object,
) -> PostApprovalReplanIdentityV1:
    if not isinstance(value, Mapping):
        raise PostApprovalReplanV2Error("post-approval replan identity must be an object")
    root = dict(value)
    expected = {
        "schema_version",
        "source_plan_id",
        "source_action_ids",
        "trigger",
        "phase",
        "preallocated_plan_id",
        "preallocated_action_ids",
    }
    if set(root) != expected or root.get("schema_version") != 1:
        raise PostApprovalReplanV2Error("post-approval replan identity keys/version are invalid")
    source_plan_id = _required_text(root.get("source_plan_id"), "source_plan_id")
    source_action_ids = _id_list(root.get("source_action_ids"), "source_action_ids")
    trigger = root.get("trigger")
    if trigger not in {"REVISE", "RETRIEVE_MORE"}:
        raise PostApprovalReplanV2Error("post-approval replan trigger is invalid")
    phase = root.get("phase")
    if phase not in {"ROLLOVER_REQUIRED", "IDENTITY_PREALLOCATED"}:
        raise PostApprovalReplanV2Error("post-approval replan phase is invalid")
    preallocated_plan_id = root.get("preallocated_plan_id")
    preallocated_action_ids = _id_list(
        root.get("preallocated_action_ids"),
        "preallocated_action_ids",
        allow_empty=True,
    )
    if phase == "ROLLOVER_REQUIRED":
        if preallocated_plan_id is not None or preallocated_action_ids:
            raise PostApprovalReplanV2Error("rollover-required identity cannot be preallocated")
    else:
        preallocated_plan_id = _required_text(preallocated_plan_id, "preallocated_plan_id")
        if not preallocated_action_ids:
            raise PostApprovalReplanV2Error("preallocated action ids are required")
        _validate_fresh_generation(
            source_plan_id=source_plan_id,
            source_action_ids=source_action_ids,
            plan_id=preallocated_plan_id,
            action_ids=preallocated_action_ids,
        )
    return cast(
        PostApprovalReplanIdentityV1,
        {
            "schema_version": 1,
            "source_plan_id": source_plan_id,
            "source_action_ids": source_action_ids,
            "trigger": trigger,
            "phase": phase,
            "preallocated_plan_id": preallocated_plan_id,
            "preallocated_action_ids": preallocated_action_ids,
        },
    )


def bind_preallocated_identity(
    *,
    identity: PostApprovalReplanIdentityV1,
    plan: ActionPlanDraftV2,
) -> PostApprovalReplanIdentityV1:
    """Bind the current official fresh V2 generation for persistence preservation."""

    current = validate_post_approval_replan_identity(identity)
    plan_id, action_ids = _plan_identity(plan)
    revision = plan["meta"]["revision"]
    if current["phase"] == "ROLLOVER_REQUIRED" and revision != 1:
        raise PostApprovalReplanV2Error(
            "a fresh post-approval artifact must start at revision 1"
        )
    _validate_fresh_generation(
        source_plan_id=current["source_plan_id"],
        source_action_ids=current["source_action_ids"],
        plan_id=plan_id,
        action_ids=action_ids,
    )
    return {
        **current,
        "phase": "IDENTITY_PREALLOCATED",
        "preallocated_plan_id": plan_id,
        "preallocated_action_ids": action_ids,
    }


def validate_preallocated_plan_identity(
    *,
    identity: PostApprovalReplanIdentityV1,
    plan_id: str,
    action_ids: Sequence[str],
) -> PostApprovalReplanIdentityV1:
    """Require a persistence DTO to preserve the exact reviewed V2 ids."""

    current = validate_post_approval_replan_identity(identity)
    if current["phase"] != "IDENTITY_PREALLOCATED":
        raise PostApprovalReplanV2Error("post-approval V2 identity is not preallocated")
    normalized_action_ids = _id_list(list(action_ids), "action_ids")
    if plan_id != current["preallocated_plan_id"]:
        raise PostApprovalReplanV2Error("persistence plan id differs from reviewed V2 plan id")
    if normalized_action_ids != current["preallocated_action_ids"]:
        raise PostApprovalReplanV2Error("persistence action ids differ from reviewed V2 action ids")
    return current


def materialize_fresh_post_approval_revise_plan(
    *,
    source_modified_plan: ActionPlanDraftV2,
    corrected_plan: ActionPlanDraftV2,
    review_result: PlanReviewResultV2,
    tool_route_plan: ToolRoutePlanV2,
    work_analysis_result: WorkAnalysisResultV2,
    retrieval_result: RetrievalResultV1,
    plan_id_factory: Callable[[], str],
    action_id_factory: Callable[[], str],
) -> ActionPlanDraftV2:
    """Promote corrected business semantics into a fresh official V2 identity.

    ``corrected_plan`` is the bounded output of the existing pre-approval
    Planning revision logic.  Its business arguments/evidence/dependencies are
    reused, but its same-generation ids are never promoted after the durable
    source plan has been superseded.
    """

    source_plan_id, source_action_ids = _plan_identity(source_modified_plan)
    corrected_plan_id, corrected_action_ids = _plan_identity(corrected_plan)
    if corrected_plan_id != source_plan_id or corrected_action_ids != source_action_ids:
        raise PostApprovalReplanV2Error(
            "post-approval business correction must not mutate identity before rollover"
        )
    if review_result["status"] != "REVISE":
        raise PostApprovalReplanV2Error("fresh post-approval revision requires Review REVISE")
    source_ref = _artifact_ref(source_modified_plan["meta"], "source modified plan")
    if source_ref not in review_result["meta"]["based_on"]:
        raise PostApprovalReplanV2Error("Review REVISE is stale for the modified source plan")

    routes = output_routes(tool_route_plan)
    route_by_id = {route["route_id"]: route for route in routes}
    corrected_by_route = {action["route_id"]: action for action in corrected_plan["actions"]}
    if len(route_by_id) != len(routes) or set(corrected_by_route) != set(route_by_id):
        raise PostApprovalReplanV2Error("corrected plan no longer matches frozen output routes")

    fresh_plan_id = _required_text(plan_id_factory(), "fresh plan id")
    fresh_action_ids: dict[str, str] = {}
    seeds: list[PlanningActionSeedV1] = []
    old_to_new: dict[str, str] = {}
    for route in routes:
        route_id = route["route_id"]
        action = corrected_by_route[route_id]
        if action["tool_id"] != route["selected_tool_id"] or action["effect"] != route["effect"]:
            raise PostApprovalReplanV2Error("corrected action escapes frozen Tool Route authority")
        fresh_action_id = _required_text(action_id_factory(), f"fresh action id for {route_id}")
        if fresh_action_id in fresh_action_ids.values():
            raise PostApprovalReplanV2Error("fresh action id factory produced duplicate ids")
        fresh_action_ids[route_id] = fresh_action_id
        old_to_new[action["action_id"]] = fresh_action_id
        seeds.append(
            {
                "action_id": fresh_action_id,
                "route_id": route_id,
                "tool_id": action["tool_id"],
                "effect": action["effect"],
                "arguments": dict(action["arguments"]),
                "evidence_refs": list(action["evidence_refs"]),
            }
        )

    dependency_candidates: list[ActionDependencyCandidateV1] = []
    for action in corrected_plan["actions"]:
        new_action_id = old_to_new[action["action_id"]]
        for old_dependency_id in action["depends_on_action_ids"]:
            dependency_id = old_to_new.get(old_dependency_id)
            if dependency_id is None:
                raise PostApprovalReplanV2Error(
                    "corrected dependency references an action outside the superseded generation"
                )
            dependency_candidates.append(
                {
                    "action_id": new_action_id,
                    "depends_on_action_id": dependency_id,
                    "reason": "POST_APPROVAL_REPLAN_IDENTITY_ROLLOVER",
                }
            )

    _validate_fresh_generation(
        source_plan_id=source_plan_id,
        source_action_ids=source_action_ids,
        plan_id=fresh_plan_id,
        action_ids=[seed["action_id"] for seed in seeds],
    )
    based_on = _ordered_unique_refs(
        [
            source_ref,
            _artifact_ref(review_result["meta"], "ReviewV2"),
            _artifact_ref(tool_route_plan["output_plan"]["meta"], "Tool Route output"),
            _artifact_ref(work_analysis_result["meta"], "WorkAnalysisResultV2"),
            _artifact_ref(retrieval_result["meta"], "RetrievalResultV1"),
        ]
    )
    try:
        return assemble_action_plan_draft_v2(
            artifact_id=fresh_plan_id,
            revision=1,
            based_on=based_on,
            action_seeds=seeds,
            dependency_candidates=dependency_candidates,
        )
    except PlanningAssemblyError as exc:
        raise PostApprovalReplanV2Error(str(exc)) from exc


def _plan_identity(plan: ActionPlanDraftV2) -> tuple[str, list[str]]:
    meta = plan.get("meta")
    if not isinstance(meta, Mapping):
        raise PostApprovalReplanV2Error("ActionPlanDraftV2 meta is missing")
    plan_id = _required_text(meta.get("artifact_id"), "plan artifact id")
    revision = meta.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PostApprovalReplanV2Error("plan artifact revision is invalid")
    raw_actions = plan.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise PostApprovalReplanV2Error("ActionPlanDraftV2 actions are missing")
    action_ids = _id_list([action.get("action_id") for action in raw_actions], "action ids")
    return plan_id, action_ids


def _validate_fresh_generation(
    *,
    source_plan_id: str,
    source_action_ids: Sequence[str],
    plan_id: str,
    action_ids: Sequence[str],
) -> None:
    if plan_id == source_plan_id:
        raise PostApprovalReplanV2Error("post-approval replan must allocate a new plan id")
    if set(source_action_ids) & set(action_ids):
        raise PostApprovalReplanV2Error("post-approval replan must allocate new action ids")
    if len(action_ids) != len(set(action_ids)):
        raise PostApprovalReplanV2Error("post-approval replan action ids are not unique")


def _artifact_ref(value: object, label: str) -> StateArtifactRefV1:
    if not isinstance(value, Mapping):
        raise PostApprovalReplanV2Error(f"{label} meta is missing")
    artifact_id = _required_text(value.get("artifact_id"), f"{label} artifact id")
    revision = value.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PostApprovalReplanV2Error(f"{label} revision is invalid")
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


def _id_list(value: object, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise PostApprovalReplanV2Error(f"{label} must be a list of non-empty ids")
    result = cast(list[str], list(value))
    if not allow_empty and not result:
        raise PostApprovalReplanV2Error(f"{label} must not be empty")
    if len(result) != len(set(result)):
        raise PostApprovalReplanV2Error(f"{label} contains duplicate ids")
    return result


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PostApprovalReplanV2Error(f"{label} is required")
    return value


__all__ = [
    "PostApprovalReplanIdentityV1",
    "PostApprovalReplanV2Error",
    "begin_post_approval_replan_identity",
    "bind_preallocated_identity",
    "materialize_fresh_post_approval_revise_plan",
    "validate_post_approval_replan_identity",
    "validate_preallocated_plan_identity",
]
