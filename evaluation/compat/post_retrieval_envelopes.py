"""Canonical SubgraphReturnV2 validation for post-Retrieval owners.

This module freezes the artifact-vs-workflow-control boundary before the Main
State cut-over.  It consumes the single canonical ``SubgraphReturnV2`` type
from ``handoff_contracts``; it does not define a competing envelope authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.planning.contracts.answer_draft import (
    AnswerDraftV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    PlanningResultV2,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.review.validate_review import validate_review
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2
from google_work_agent.ports.system.contracts.workflow_signal import (
    SubgraphReturnV2,
)

PostRetrievalSubgraphReturnV2 = SubgraphReturnV2[object]

_WORK_ANALYSIS_DISPOSITIONS = {
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
}
_PLANNING_DISPOSITIONS = {
    "ANSWER_ONLY",
    "PLAN_READY",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
}
_REVIEW_DISPOSITIONS = {
    "PASS",
    "REVISE",
    "RETRIEVE_MORE",
    "ROUTE_RECONSIDERATION",
    "CONFIRM",
    "BLOCK",
}


class PostRetrievalEnvelopeV2Error(ValueError):
    """SubgraphReturnV2 violates canonical artifact/signal ownership rules."""


def validate_work_analysis_return_v2(value: object) -> PostRetrievalSubgraphReturnV2:
    envelope = _envelope(value, allowed=_WORK_ANALYSIS_DISPOSITIONS)
    disposition = envelope["disposition"]
    result = envelope["typed_result"]
    signal = envelope["workflow_signal"]

    if disposition == "COMPLETE":
        _work_analysis_artifact(result)
        _require_no_signal(signal, disposition)
    else:
        _require_no_artifact(result, disposition)
        if disposition == "NEEDS_MORE_DATA":
            _require_signal_kind(
                signal,
                {"RETRIEVAL_REQUIRED", "ROUTE_RECONSIDERATION_REQUIRED"},
                disposition,
            )
        elif disposition == "NEEDS_CONFIRMATION":
            _require_signal_kind(signal, {"CONFIRMATION_REQUIRED"}, disposition)
        elif disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            _require_signal_kind(signal, {"ROUTE_RECONSIDERATION_REQUIRED"}, disposition)
        else:
            _require_signal_kind(signal, {"BLOCKED"}, disposition)
    return envelope


def validate_planning_return_v2(value: object) -> PostRetrievalSubgraphReturnV2:
    envelope = _envelope(value, allowed=_PLANNING_DISPOSITIONS)
    disposition = envelope["disposition"]
    result = envelope["typed_result"]
    signal = envelope["workflow_signal"]

    if disposition == "ANSWER_ONLY":
        _answer_artifact(result)
        _require_no_signal(signal, disposition)
    elif disposition == "PLAN_READY":
        _action_plan_artifact(result)
        _require_no_signal(signal, disposition)
    else:
        _require_no_artifact(result, disposition)
        if disposition == "NEEDS_CONFIRMATION":
            _require_signal_kind(signal, {"CONFIRMATION_REQUIRED"}, disposition)
        elif disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            _require_signal_kind(signal, {"ROUTE_RECONSIDERATION_REQUIRED"}, disposition)
        else:
            _require_signal_kind(signal, {"BLOCKED"}, disposition)
    return envelope


def validate_review_return_v2(value: object) -> PostRetrievalSubgraphReturnV2:
    envelope = _envelope(value, allowed=_REVIEW_DISPOSITIONS)
    disposition = envelope["disposition"]
    result = envelope["typed_result"]
    signal = envelope["workflow_signal"]

    _review_artifact(result, expected_status=disposition)
    if disposition in {"PASS", "REVISE"}:
        _require_no_signal(signal, disposition)
    elif disposition == "RETRIEVE_MORE":
        _require_signal_kind(
            signal,
            {"RETRIEVAL_REQUIRED", "ROUTE_RECONSIDERATION_REQUIRED"},
            disposition,
        )
    elif disposition == "ROUTE_RECONSIDERATION":
        _require_signal_kind(signal, {"ROUTE_RECONSIDERATION_REQUIRED"}, disposition)
    elif disposition == "CONFIRM":
        _require_signal_kind(signal, {"CONFIRMATION_REQUIRED"}, disposition)
    else:
        _require_signal_kind(signal, {"BLOCKED"}, disposition)
    return envelope


def _envelope(value: object, *, allowed: set[str]) -> PostRetrievalSubgraphReturnV2:
    root = _mapping(value, "$")
    expected = {"disposition", "typed_result", "workflow_signal"}
    if set(root) != expected:
        raise PostRetrievalEnvelopeV2Error("SubgraphReturnV2 keys are invalid")
    disposition = root["disposition"]
    if not isinstance(disposition, str) or disposition not in allowed:
        raise PostRetrievalEnvelopeV2Error("SubgraphReturnV2.disposition is invalid")
    signal = root["workflow_signal"]
    if signal is not None and not isinstance(signal, Mapping):
        raise PostRetrievalEnvelopeV2Error("workflow_signal must be an object or null")
    return cast(PostRetrievalSubgraphReturnV2, dict(root))


def _work_analysis_artifact(value: object) -> WorkAnalysisResultV2:
    root = _mapping(value, "typed_result")
    expected = {
        "schema_version",
        "meta",
        "work_facts",
        "relations",
        "ambiguities",
        "risks",
        "evidence_refs",
        "policy_confirmation_receipt_refs",
        "action_necessity",
    }
    if set(root) != expected or root.get("schema_version") != 2:
        raise PostRetrievalEnvelopeV2Error("COMPLETE requires WorkAnalysisResultV2")
    _artifact_meta(root.get("meta"), "typed_result.meta")
    if root.get("action_necessity") not in {"REQUIRED", "NOT_REQUIRED"}:
        raise PostRetrievalEnvelopeV2Error("WorkAnalysisResultV2.action_necessity is invalid")
    return cast(WorkAnalysisResultV2, root)


def _answer_artifact(value: object) -> AnswerDraftV2:
    root = _mapping(value, "typed_result")
    if set(root) != {"schema_version", "meta", "answer", "evidence_refs"}:
        raise PostRetrievalEnvelopeV2Error("ANSWER_ONLY requires AnswerDraftV2")
    if root.get("schema_version") != 2 or not isinstance(root.get("answer"), str):
        raise PostRetrievalEnvelopeV2Error("ANSWER_ONLY requires AnswerDraftV2")
    _artifact_meta(root.get("meta"), "typed_result.meta")
    _string_list(root.get("evidence_refs"), "typed_result.evidence_refs")
    return cast(AnswerDraftV2, root)


def _action_plan_artifact(value: object) -> ActionPlanDraftV2:
    root = _mapping(value, "typed_result")
    if set(root) != {"schema_version", "meta", "actions"} or root.get("schema_version") != 2:
        raise PostRetrievalEnvelopeV2Error("PLAN_READY requires ActionPlanDraftV2")
    _artifact_meta(root.get("meta"), "typed_result.meta")
    actions = root.get("actions")
    if not isinstance(actions, list) or not actions:
        raise PostRetrievalEnvelopeV2Error("ActionPlanDraftV2.actions must not be empty")
    return cast(ActionPlanDraftV2, root)


def _review_artifact(value: object, *, expected_status: str) -> PlanReviewResultV2:
    root = _mapping(value, "typed_result")
    if root.get("schema_version") != 2 or root.get("status") != expected_status:
        raise PostRetrievalEnvelopeV2Error("Review typed_result status must match disposition")
    _artifact_meta(root.get("meta"), "typed_result.meta")
    try:
        validate_review(root)
    except ValueError as error:
        raise PostRetrievalEnvelopeV2Error(str(error)) from error
    return cast(PlanReviewResultV2, root)


def _require_no_artifact(value: object, disposition: str) -> None:
    if value is not None:
        raise PostRetrievalEnvelopeV2Error(
            f"{disposition} must not promote an incomplete business artifact"
        )


def _require_no_signal(value: object, disposition: str) -> None:
    if value is not None:
        raise PostRetrievalEnvelopeV2Error(f"{disposition} must not carry workflow_signal")


def _require_signal_kind(value: object, kinds: set[str], disposition: str) -> None:
    signal = _mapping(value, "workflow_signal")
    kind = signal.get("kind")
    if kind not in kinds:
        raise PostRetrievalEnvelopeV2Error(
            f"{disposition} requires workflow_signal kind in {sorted(kinds)}"
        )
    if kind == "RETRIEVAL_REQUIRED":
        _retrieval_signal(signal)
    elif kind == "CONFIRMATION_REQUIRED":
        _confirmation_signal(signal)
    else:
        _reason_signal(signal, kind=cast(str, kind))


def _retrieval_signal(signal: Mapping[str, object]) -> None:
    if set(signal) != {"kind", "reason_codes", "needs"}:
        raise PostRetrievalEnvelopeV2Error("RetrievalRequiredV1 keys are invalid")
    _non_empty_string_list(signal.get("reason_codes"), "workflow_signal.reason_codes")
    needs = signal.get("needs")
    if not isinstance(needs, list) or not needs:
        raise PostRetrievalEnvelopeV2Error("RetrievalRequiredV1.needs must not be empty")
    for index, raw in enumerate(needs):
        item = _mapping(raw, f"workflow_signal.needs[{index}]")
        if set(item) != {"required_information", "reason_codes"}:
            raise PostRetrievalEnvelopeV2Error("RetrievalNeedV1 keys are invalid")
        text = item.get("required_information")
        if not isinstance(text, str) or not text:
            raise PostRetrievalEnvelopeV2Error("RetrievalNeedV1.required_information is required")
        _non_empty_string_list(item.get("reason_codes"), "RetrievalNeedV1.reason_codes")


def _confirmation_signal(signal: Mapping[str, object]) -> None:
    expected = {"kind", "interrupt_id", "semantic_owner_id", "resume_target", "question", "options"}
    if set(signal) != expected:
        raise PostRetrievalEnvelopeV2Error("ConfirmationRequiredV1 keys are invalid")
    for field in ("interrupt_id", "semantic_owner_id", "question"):
        item = signal.get(field)
        if not isinstance(item, str) or not item:
            raise PostRetrievalEnvelopeV2Error(f"ConfirmationRequiredV1.{field} is required")
    _string_list(signal.get("options"), "ConfirmationRequiredV1.options")
    resume = signal.get("resume_target")
    if not isinstance(resume, AgentNodeResumeTargetV2):
        raise PostRetrievalEnvelopeV2Error(
            "ConfirmationRequiredV1.resume_target must be AgentNodeResumeTargetV2"
        )
    if resume.semantic_owner_id != signal["semantic_owner_id"]:
        raise PostRetrievalEnvelopeV2Error("confirmation owner/resume target mismatch")


def _reason_signal(signal: Mapping[str, object], *, kind: str) -> None:
    if set(signal) != {"kind", "reason_codes"}:
        raise PostRetrievalEnvelopeV2Error(f"{kind} signal keys are invalid")
    _non_empty_string_list(signal.get("reason_codes"), "workflow_signal.reason_codes")


def _artifact_meta(value: object, path: str) -> None:
    meta = _mapping(value, path)
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise PostRetrievalEnvelopeV2Error(f"{path} keys are invalid")
    if not isinstance(meta.get("artifact_id"), str) or not meta["artifact_id"]:
        raise PostRetrievalEnvelopeV2Error(f"{path}.artifact_id is required")
    revision = meta.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PostRetrievalEnvelopeV2Error(f"{path}.revision is invalid")
    based_on = meta.get("based_on")
    if not isinstance(based_on, list):
        raise PostRetrievalEnvelopeV2Error(f"{path}.based_on must be an array")
    for index, raw in enumerate(based_on):
        ref = _mapping(raw, f"{path}.based_on[{index}]")
        if set(ref) != {"artifact_id", "revision"}:
            raise PostRetrievalEnvelopeV2Error(f"{path}.based_on[{index}] keys are invalid")
        if not isinstance(ref.get("artifact_id"), str) or not ref["artifact_id"]:
            raise PostRetrievalEnvelopeV2Error(f"{path}.based_on[{index}].artifact_id is required")
        ref_revision = ref.get("revision")
        if not isinstance(ref_revision, int) or isinstance(ref_revision, bool) or ref_revision < 1:
            raise PostRetrievalEnvelopeV2Error(f"{path}.based_on[{index}].revision is invalid")


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PostRetrievalEnvelopeV2Error(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PostRetrievalEnvelopeV2Error(f"{path} keys must be strings")
        result[key] = item
    return result


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PostRetrievalEnvelopeV2Error(f"{path} must be a string array")
    return cast(list[str], list(value))


def _non_empty_string_list(value: object, path: str) -> list[str]:
    values = _string_list(value, path)
    if not values or any(not item for item in values):
        raise PostRetrievalEnvelopeV2Error(f"{path} must contain non-empty strings")
    return values


__all__ = [
    "PlanningResultV2",
    "PostRetrievalEnvelopeV2Error",
    "PostRetrievalSubgraphReturnV2",
    "validate_planning_return_v2",
    "validate_review_return_v2",
    "validate_work_analysis_return_v2",
]
