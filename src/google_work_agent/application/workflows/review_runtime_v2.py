"""Checkpoint-B Review V2 producer and workflow-signal projection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Callable, Protocol, cast

from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalNeedV1,
    RetrievalResultV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
    SubgraphReturnV2,
)
from google_work_agent.application.workflows.planning_plan_assembler import ActionPlanDraftV2
from google_work_agent.application.workflows.post_retrieval_envelopes_v2 import (
    PlanningResultV2,
    validate_review_return_v2,
)
from google_work_agent.application.workflows.review_v2 import (
    PlanReviewCandidateV2,
    materialize_plan_review_result_v2,
    validate_plan_review_candidate_v2,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)

RetrievalNeedSatisfier = Callable[[Sequence[RetrievalNeedV1]], bool]


class ReviewCandidateProvider(Protocol):
    """Invocation-local semantic Review candidate owner."""

    def inspect(
        self,
        *,
        request_intent: RequestIntentV2,
        work_analysis_result: WorkAnalysisResultV2,
        planning_result: PlanningResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
    ) -> object: ...


class ReviewV2RuntimeError(ValueError):
    pass


class ReviewV2Producer:
    def __init__(
        self,
        *,
        candidate_provider: ReviewCandidateProvider,
        artifact_id_factory: Callable[[], str],
        retrieval_need_satisfier: RetrievalNeedSatisfier | None = None,
    ) -> None:
        self._candidate_provider = candidate_provider
        self._artifact_id_factory = artifact_id_factory
        self._retrieval_need_satisfier = retrieval_need_satisfier

    def run(
        self,
        *,
        request_intent: RequestIntentV2,
        retrieval_result: RetrievalResultV1,
        work_analysis_result: WorkAnalysisResultV2,
        planning_result: PlanningResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
        interrupt_id: str | None = None,
        resume_target: RegisteredResumeTargetRefV1 | None = None,
    ) -> SubgraphReturnV2[PlanReviewResultV2]:
        evidence = _validate_current_evidence(
            evidence_drafts,
            expected_refs=retrieval_result["evidence_refs"],
        )
        _validate_current_planning_lineage(
            planning_result=planning_result,
            work_analysis_result=work_analysis_result,
            retrieval_result=retrieval_result,
        )
        candidate = validate_plan_review_candidate_v2(
            self._candidate_provider.inspect(
                request_intent=request_intent,
                work_analysis_result=work_analysis_result,
                planning_result=planning_result,
                evidence_drafts=evidence,
            )
        )
        review = materialize_plan_review_result_v2(
            cast(PlanReviewCandidateV2, candidate),
            meta=_review_meta(
                artifact_id=_required_id(self._artifact_id_factory(), "review artifact id"),
                planning_result=planning_result,
            ),
        )
        signal = _review_signal(
            review,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
            retrieval_need_satisfier=self._retrieval_need_satisfier,
        )
        return cast(
            SubgraphReturnV2[PlanReviewResultV2],
            validate_review_return_v2(
                {
                    "disposition": review["status"],
                    "typed_result": review,
                    "workflow_signal": signal,
                }
            ),
        )


def _review_signal(
    review: PlanReviewResultV2,
    *,
    interrupt_id: str | None,
    resume_target: RegisteredResumeTargetRefV1 | None,
    retrieval_need_satisfier: RetrievalNeedSatisfier | None,
) -> dict[str, object] | None:
    status = review["status"]
    if status in {"PASS", "REVISE"}:
        return None
    if status == "RETRIEVE_MORE":
        needs: list[RetrievalNeedV1] = []
        for gap in review["evidence_gaps"]:
            for required_information in gap["required_information"]:
                needs.append(
                    {
                        "required_information": required_information,
                        "reason_codes": [gap["code"]],
                    }
                )
        if not needs:
            raise ReviewV2RuntimeError("RETRIEVE_MORE requires at least one RetrievalNeedV1")
        reason_codes = _ordered_unique(
            code for need in needs for code in need["reason_codes"]
        )
        if retrieval_need_satisfier is not None and not retrieval_need_satisfier(needs):
            return {
                "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                "reason_codes": reason_codes,
            }
        return {
            "kind": "RETRIEVAL_REQUIRED",
            "reason_codes": reason_codes,
            "needs": needs,
        }
    if status == "ROUTE_RECONSIDERATION":
        reason_codes = _ordered_unique(issue["code"] for issue in review["route_issues"])
        if not reason_codes:
            raise ReviewV2RuntimeError("ROUTE_RECONSIDERATION requires reason codes")
        return {
            "kind": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": reason_codes,
        }
    if status == "CONFIRM":
        if interrupt_id is None or resume_target is None:
            raise ReviewV2RuntimeError(
                "Application-owned interrupt_id and resume_target are required for Review confirmation"
            )
        if resume_target.get("subgraph_id") != "REVIEW":
            raise ReviewV2RuntimeError("Review confirmation must resume REVIEW")
        confirmation = review["confirmation"]
        return {
            "kind": "CONFIRMATION_REQUIRED",
            "interrupt_id": _required_id(interrupt_id, "interrupt_id"),
            "owner_subgraph": "REVIEW",
            "resume_target": _resume_target(resume_target),
            "question": confirmation["question"],
            "options": list(confirmation["options"]),
        }
    reason_codes = _ordered_unique(blocker["code"] for blocker in review["blockers"])
    if not reason_codes:
        raise ReviewV2RuntimeError("BLOCK requires reason codes")
    return {"kind": "BLOCKED", "reason_codes": reason_codes}


def _validate_current_planning_lineage(
    *,
    planning_result: PlanningResultV2,
    work_analysis_result: WorkAnalysisResultV2,
    retrieval_result: RetrievalResultV1,
) -> None:
    based_on = planning_result["meta"]["based_on"]
    if _artifact_ref(work_analysis_result["meta"]) not in based_on:
        raise ReviewV2RuntimeError("stale PlanningResultV2 for current WorkAnalysisResultV2")
    if _artifact_ref(retrieval_result["meta"]) not in based_on:
        raise ReviewV2RuntimeError("stale PlanningResultV2 for current RetrievalResultV1")


def _review_meta(
    *,
    artifact_id: str,
    planning_result: PlanningResultV2,
) -> StateArtifactMetaV1:
    return {
        "artifact_id": artifact_id,
        "revision": 1,
        "based_on": [_artifact_ref(planning_result["meta"])],
    }


def _artifact_ref(meta: Mapping[str, object]) -> StateArtifactRefV1:
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ReviewV2RuntimeError("artifact meta id is invalid")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise ReviewV2RuntimeError("artifact meta revision is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _validate_current_evidence(
    evidence_drafts: Sequence[EvidenceDraftV1],
    *,
    expected_refs: Sequence[str],
) -> list[EvidenceDraftV1]:
    expected = list(expected_refs)
    if len(expected) != len(set(expected)):
        raise ReviewV2RuntimeError("RetrievalResultV1.evidence_refs contains duplicates")
    by_id: dict[str, EvidenceDraftV1] = {}
    for draft in evidence_drafts:
        evidence_id = draft["evidence_id"]
        if evidence_id in by_id:
            raise ReviewV2RuntimeError("duplicate current-run evidence id")
        by_id[evidence_id] = draft
    if set(by_id) != set(expected):
        raise ReviewV2RuntimeError("Review evidence does not match current RetrievalResultV1")
    return [by_id[evidence_id] for evidence_id in expected]


def _resume_target(value: RegisteredResumeTargetRefV1) -> RegisteredResumeTargetRefV1:
    expected = {"subgraph_id", "node_id", "graph_version"}
    if set(value) != expected:
        raise ReviewV2RuntimeError("RegisteredResumeTargetRefV1 keys are invalid")
    for field in expected:
        _required_id(value[field], f"resume_target.{field}")
    return cast(RegisteredResumeTargetRefV1, dict(value))


def _required_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewV2RuntimeError(f"{label} is required")
    return value


def _ordered_unique(values: Sequence[str] | object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:  # type: ignore[union-attr]
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "ReviewCandidateProvider",
    "ReviewV2Producer",
    "ReviewV2RuntimeError",
]
