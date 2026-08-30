"""Deterministic PlanReviewResultV2 -> WorkflowSignalV1 projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.review.validate_review import validate_review
from google_work_agent.application.orchestration.handoff_contracts import (
    BlockedSignalV1,
    ConfirmationRequiredV1,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
    WorkflowSignalV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


class ReviewV2SignalProjectionError(ValueError):
    """A canonical Review result lacks the data required by its workflow signal."""


def project_review_workflow_signal_v2(
    result: PlanReviewResultV2,
    *,
    interrupt_id: str | None = None,
    resume_target: AgentNodeResumeTargetV2 | None = None,
) -> WorkflowSignalV1 | None:
    review = _validated_review(result)
    status = cast(str, review["status"])
    if status in {"PASS", "REVISE"}:
        return None
    if status == "RETRIEVE_MORE":
        return _retrieval_required(review)
    if status == "ROUTE_RECONSIDERATION":
        return _route_reconsideration(review)
    if status == "CONFIRM":
        return _confirmation_required(
            review,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )
    return _blocked(review)


def _retrieval_required(review: Mapping[str, object]) -> RetrievalRequiredV1:
    raw_gaps = review.get("evidence_gaps")
    if not isinstance(raw_gaps, list):
        raise ReviewV2SignalProjectionError("RETRIEVE_MORE requires evidence_gaps")
    needs: list[RetrievalNeedV1] = []
    reason_codes: list[str] = []
    for gap in raw_gaps:
        if not isinstance(gap, Mapping):
            raise ReviewV2SignalProjectionError("evidence gap must be an object")
        code = _text(gap.get("code"), "evidence gap code")
        if code not in reason_codes:
            reason_codes.append(code)
        required_information = gap.get("required_information")
        if not isinstance(required_information, list):
            raise ReviewV2SignalProjectionError(
                "evidence gap required_information must be an array"
            )
        for raw_information in required_information:
            information = _text(raw_information, "required information")
            needs.append(
                {
                    "required_information": information,
                    "reason_codes": [code],
                }
            )
    if not needs or not reason_codes:
        raise ReviewV2SignalProjectionError(
            "RETRIEVE_MORE must project at least one RetrievalNeedV1"
        )
    return {
        "kind": "RETRIEVAL_REQUIRED",
        "reason_codes": reason_codes,
        "needs": needs,
    }


def _route_reconsideration(review: Mapping[str, object]) -> RouteReconsiderationRequiredV1:
    raw_issues = review.get("route_issues")
    if not isinstance(raw_issues, list):
        raise ReviewV2SignalProjectionError("ROUTE_RECONSIDERATION requires route_issues")
    reason_codes = _unique_codes(raw_issues, label="route issue")
    if not reason_codes:
        raise ReviewV2SignalProjectionError(
            "ROUTE_RECONSIDERATION requires at least one route issue code"
        )
    return {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": reason_codes,
    }


def _confirmation_required(
    review: Mapping[str, object],
    *,
    interrupt_id: str | None,
    resume_target: AgentNodeResumeTargetV2 | None,
) -> ConfirmationRequiredV1:
    if not isinstance(interrupt_id, str) or not interrupt_id:
        raise ReviewV2SignalProjectionError("CONFIRM requires runtime interrupt_id")
    if resume_target is None:
        raise ReviewV2SignalProjectionError("CONFIRM requires registered resume_target")
    _validate_resume_target(resume_target)
    confirmation = review.get("confirmation")
    if not isinstance(confirmation, Mapping):
        raise ReviewV2SignalProjectionError("CONFIRM requires confirmation")
    question = _text(confirmation.get("question"), "confirmation question")
    raw_options = confirmation.get("options")
    if not isinstance(raw_options, list):
        raise ReviewV2SignalProjectionError("confirmation options must be an array")
    options = [_text(item, "confirmation option") for item in raw_options]
    return {
        "kind": "CONFIRMATION_REQUIRED",
        "interrupt_id": interrupt_id,
        "semantic_owner_id": "REVIEW",
        "resume_target": resume_target,
        "question": question,
        "options": options,
    }


def _blocked(review: Mapping[str, object]) -> BlockedSignalV1:
    raw_blockers = review.get("blockers")
    if not isinstance(raw_blockers, list):
        raise ReviewV2SignalProjectionError("BLOCK requires blockers")
    reason_codes = _unique_codes(raw_blockers, label="blocker")
    if not reason_codes:
        raise ReviewV2SignalProjectionError("BLOCK requires at least one blocker code")
    return {"kind": "BLOCKED", "reason_codes": reason_codes}


def _validated_review(result: PlanReviewResultV2) -> dict[str, object]:
    try:
        return cast(dict[str, object], validate_review(result))
    except ValueError as error:
        raise ReviewV2SignalProjectionError(str(error)) from error


def _unique_codes(items: list[object], *, label: str) -> list[str]:
    result: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ReviewV2SignalProjectionError(f"{label} must be an object")
        code = _text(item.get("code"), f"{label} code")
        if code not in result:
            result.append(code)
    return result


def _validate_resume_target(value: AgentNodeResumeTargetV2) -> None:
    if not isinstance(value, AgentNodeResumeTargetV2):
        raise ReviewV2SignalProjectionError("resume_target must be AgentNodeResumeTargetV2")
    if value.semantic_owner_id != "REVIEW":
        raise ReviewV2SignalProjectionError(
            "Review confirmation resume_target must belong to REVIEW"
        )


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewV2SignalProjectionError(f"{label} must be a non-empty string")
    return value


__all__ = [
    "ReviewV2SignalProjectionError",
    "project_review_workflow_signal_v2",
]
