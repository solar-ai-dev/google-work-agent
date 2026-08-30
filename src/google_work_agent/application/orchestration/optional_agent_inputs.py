"""Canonical optional-input helpers for SIX_ROLE Work Analysis and Planning.

Workflow v7.20 explicitly permits two production paths that the legacy V1
agents did not model:

* Tool Route may enter Work Analysis without a Retrieval invocation.
* Planning may run with no Work Analysis when effective analysis is not
  required, and may also receive Retrieval evidence directly without an
  analysis artifact.

These helpers preserve that absence as ``None``/empty evidence. They never
manufacture fake RetrievalResultV1 or WorkAnalysisResultV1 artifacts merely
to satisfy legacy function signatures.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import cast

import google_work_agent.application.orchestration.solution_planning as _planning
import google_work_agent.application.orchestration.work_analysis_result_v1_validation as _analysis
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    EvidenceDraftV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    assemble_action_plan_draft_v2,
    materialize_action_seeds,
)
from google_work_agent.application.use_cases.verification.write_verification_projection import (
    build_expected_verification_projection,
)


def validate_work_analysis_without_retrieval(value: object) -> WorkAnalysisResultV1:
    """Validate Work Analysis against an intentionally empty reference space."""

    return _analysis._validate_work_analysis_result_v1_core(
        value,
        refs={
            "evidence_ids": set(),
            "resource_handles": set(),
            "segment_ids": set(),
        },
    )


def assemble_plan_with_optional_analysis(
    *,
    request_intent: RequestIntentV2,
    analysis_result: WorkAnalysisResultV1 | None,
    evidence_drafts: list[EvidenceDraftV1],
    output_routes: tuple[OutputToolRouteV1, ...],
    argument_candidates: tuple[object, ...],
    plan_id_factory: Callable[[], str],
    action_id_factory: Callable[[], str],
    previous_plan: ActionPlanDraftV1 | None,
) -> ActionPlanDraftV1:
    """Assemble an ACTION plan without inventing a Work Analysis artifact."""

    if analysis_result is not None:
        return _planning_plan_with_analysis(
            request_intent=request_intent,
            analysis_result=analysis_result,
            evidence_drafts=evidence_drafts,
            output_routes=output_routes,
            argument_candidates=argument_candidates,
            plan_id_factory=plan_id_factory,
            action_id_factory=action_id_factory,
            previous_plan=previous_plan,
        )

    from google_work_agent.application.orchestration.planning_arguments import (
        ToolArgumentCandidateV1,
    )

    candidates = cast(tuple[ToolArgumentCandidateV1, ...], argument_candidates)
    plan_id = previous_plan["plan_id"] if previous_plan is not None else plan_id_factory()
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("plan id must not be empty")

    action_id_by_route: dict[str, str] | None = None
    if previous_plan is not None:
        write_actions = [
            action for action in previous_plan["actions"] if action["effect"] != "READ"
        ]
        if len(write_actions) != len(output_routes):
            raise ValueError("previous plan does not align with frozen output routes")
        action_id_by_route = {}
        for route, action in zip(output_routes, write_actions, strict=True):
            if (
                action["tool_name"] != route["selected_tool_id"]
                or action["effect"] != route["effect"]
            ):
                raise ValueError("previous action does not align with frozen output route")
            action_id_by_route[route["route_id"]] = action["action_id"]

    seeds = materialize_action_seeds(
        output_routes=output_routes,
        argument_candidates=candidates,
        action_id_factory=action_id_factory,
        action_id_by_route=action_id_by_route,
    )
    intent_meta = request_intent["meta"]
    canonical = assemble_action_plan_draft_v2(
        artifact_id=plan_id,
        revision=1,
        based_on=[
            {
                "artifact_id": intent_meta["artifact_id"],
                "revision": intent_meta["revision"],
            }
        ],
        action_seeds=seeds,
    )

    evidence_by_id = {draft["evidence_id"]: draft for draft in evidence_drafts}
    plan_evidence_refs = _stable_unique(
        evidence_ref for action in canonical["actions"] for evidence_ref in action["evidence_refs"]
    )
    resource_handles = _stable_unique(
        evidence_by_id[evidence_ref]["resource_handle"]
        for evidence_ref in plan_evidence_refs
        if evidence_ref in evidence_by_id and evidence_by_id[evidence_ref]["resource_handle"]
    )
    resource_refs = [{"resource_handle": handle} for handle in resource_handles]

    legacy_actions: list[dict[str, object]] = []
    for position, planned_action in enumerate(canonical["actions"], start=1):
        action_resource_handles = _stable_unique(
            evidence_by_id[evidence_ref]["resource_handle"]
            for evidence_ref in planned_action["evidence_refs"]
            if evidence_ref in evidence_by_id and evidence_by_id[evidence_ref]["resource_handle"]
        )
        legacy_actions.append(
            {
                "schema_version": 2,
                "action_id": planned_action["action_id"],
                "position": position,
                "effect": planned_action["effect"],
                "tool_name": planned_action["tool_id"],
                "arguments": dict(planned_action["arguments"]),
                "expected": build_expected_verification_projection(
                    tool_name=planned_action["tool_id"], arguments=planned_action["arguments"]
                ),
                "evidence_refs": list(planned_action["evidence_refs"]),
                "resource_refs": action_resource_handles,
                "target_resource_ref_id": None,
                "depends_on_action_ids": list(planned_action["depends_on_action_ids"]),
                "user_visible_reason": request_intent["goal"],
            }
        )

    return cast(
        ActionPlanDraftV1,
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": plan_id,
            "summary": request_intent["goal"],
            "objective": request_intent["goal"],
            "actions": legacy_actions,
            "evidence_refs": plan_evidence_refs,
            "resource_refs": resource_refs,
            "confirmation": None,
        },
    )


def validate_plan_with_optional_analysis(
    value: ActionPlanDraftV1,
    *,
    analysis_result: WorkAnalysisResultV1 | None,
    evidence_drafts: list[EvidenceDraftV1],
    frozen_output_routes: tuple[OutputToolRouteV1, ...] | None,
    frozen_read_tool_ids: frozenset[str],
) -> ActionPlanDraftV1:
    """Revalidate code-assembled plans without fabricating Work Analysis."""

    if analysis_result is not None:
        return _planning.validate_action_plan_draft_v1(
            value,
            analysis_result=analysis_result,
            frozen_output_routes=frozen_output_routes,
            frozen_read_tool_ids=frozen_read_tool_ids,
        )

    allowed_evidence = {draft["evidence_id"] for draft in evidence_drafts}
    allowed_resources = {
        draft["resource_handle"] for draft in evidence_drafts if draft["resource_handle"]
    }
    if any(ref not in allowed_evidence for ref in value["evidence_refs"]):
        raise _planning.SolutionPlanningValidationError("plan evidence reference does not exist")
    for resource_ref in value["resource_refs"]:
        handle = resource_ref.get("resource_handle")
        if not isinstance(handle, str) or handle not in allowed_resources:
            raise _planning.SolutionPlanningValidationError(
                "plan resource reference does not exist"
            )
    action_ids = {action["action_id"] for action in value["actions"]}
    if len(action_ids) != len(value["actions"]):
        raise _planning.SolutionPlanningValidationError("duplicate action_id in plan draft")
    for action in value["actions"]:
        if any(ref not in allowed_evidence for ref in action["evidence_refs"]):
            raise _planning.SolutionPlanningValidationError(
                "action evidence reference does not exist"
            )
        if any(ref not in allowed_resources for ref in action["resource_refs"]):
            raise _planning.SolutionPlanningValidationError(
                "action resource reference does not exist"
            )
        if any(dep not in action_ids for dep in action["depends_on_action_ids"]):
            raise _planning.SolutionPlanningValidationError("action dependency not found")
    _planning._validate_action_plan_invariant(value)
    if frozen_output_routes is not None:
        _planning._validate_frozen_output_routes(
            value,
            frozen_output_routes,
            frozen_read_tool_ids=frozen_read_tool_ids,
        )
    return value


def _planning_plan_with_analysis(**kwargs: object) -> ActionPlanDraftV1:
    from google_work_agent.application.orchestration.planning_plan_assembler import (
        assemble_action_plan_draft_v1_compat,
    )

    return assemble_action_plan_draft_v1_compat(**kwargs)  # type: ignore[arg-type]


def _stable_unique(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = [
    "assemble_plan_with_optional_analysis",
    "validate_plan_with_optional_analysis",
    "validate_work_analysis_without_retrieval",
]
