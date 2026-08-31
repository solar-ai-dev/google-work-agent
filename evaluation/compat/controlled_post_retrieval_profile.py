"""Legacy replay projection owned only by controlled post-retrieval evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.solution_planning import (
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)


class ProfilePlanningProjectionV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: Literal["ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"]
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None


class ControlledReplayProjectionError(ValueError):
    """A historical controlled-replay planning projection is invalid."""


def validate_profile_planning_projection_v1(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
) -> ProfilePlanningProjectionV1:
    if not isinstance(value, Mapping):
        raise ControlledReplayProjectionError("planning projection must be an object")
    root = dict(value)
    expected = {"schema_version", "status", "answer_draft", "plan_draft"}
    if set(root) != expected or root.get("schema_version") != 2:
        raise ControlledReplayProjectionError("planning projection contract mismatch")
    status = root.get("status")
    if status not in {"ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"}:
        raise ControlledReplayProjectionError("planning projection status is invalid")
    answer_draft = (
        None
        if root["answer_draft"] is None
        else validate_answer_draft_v1(root["answer_draft"], analysis_result=analysis_result)
    )
    plan_draft = (
        None
        if root["plan_draft"] is None
        else validate_action_plan_draft_v1(root["plan_draft"], analysis_result=analysis_result)
    )
    result: ProfilePlanningProjectionV1 = {
        "schema_version": 2,
        "status": cast(
            Literal["ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
            status,
        ),
        "answer_draft": answer_draft,
        "plan_draft": plan_draft,
    }
    _require_discriminated_payload(result)
    return result


def _require_discriminated_payload(result: ProfilePlanningProjectionV1) -> None:
    status = result["status"]
    answer, plan = result["answer_draft"], result["plan_draft"]
    if status == "ANSWER_ONLY" and (answer is None or plan is not None):
        raise ControlledReplayProjectionError("ANSWER_ONLY payload mismatch")
    if status == "PLAN_READY" and (plan is None or answer is not None):
        raise ControlledReplayProjectionError("PLAN_READY payload mismatch")
    if status in {"NEEDS_CONFIRMATION", "BLOCKED"}:
        if answer is None and plan is None:
            raise ControlledReplayProjectionError(f"{status} requires one draft")
        if answer is not None and answer["status"] != status:
            raise ControlledReplayProjectionError(f"{status} answer payload mismatch")
        if plan is not None and plan["status"] != status:
            raise ControlledReplayProjectionError(f"{status} plan payload mismatch")


__all__ = ["ProfilePlanningProjectionV1", "validate_profile_planning_projection_v1"]
