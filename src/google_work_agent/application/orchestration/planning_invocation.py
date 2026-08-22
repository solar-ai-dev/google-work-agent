"""Checkpoint-B Planning V2 producer.

The producer consumes only current official upstream artifacts. ANSWER promotes
an AnswerDraftCandidateV2 into AnswerDraftV2. ACTION uses the frozen Tool Route
through ``prepare_actions`` then ``compose_prepared`` and deterministic plan
assembly. Non-COMPLETE dispositions carry workflow control only and never
promote a partial PlanningResultV2.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Literal, Protocol, TypedDict, cast

from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalResultV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
    SubgraphReturnV2,
)
from google_work_agent.application.orchestration.assemble_planning_answer import (
    AnswerDraftCandidateV2,
    materialize_answer_draft_v2,
    validate_answer_draft_candidate_v2,
)
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    PlanningActionPreparationResultV1,
    project_planning_action_confirmation_required_v1,
)
from google_work_agent.application.orchestration.compose_planning_arguments import (
    PlanningArgumentOrchestratorV2,
)
from google_work_agent.application.orchestration.planning_plan_assembler import (
    assemble_action_plan_draft_v2,
    materialize_action_seeds,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import (
    PlanningResultV2,
    validate_planning_return_v2,
)
from google_work_agent.application.orchestration.state_artifacts import WorkAnalysisResultV2
from google_work_agent.application.orchestration.tool_routing import (
    ToolRoutePlanV2,
    output_routes,
)
from google_work_agent.ports import WorkflowStartRequest


class PlanningSemanticCompleteV1(TypedDict):
    disposition: Literal["COMPLETE"]


class PlanningSemanticNeedsConfirmationV1(TypedDict):
    disposition: Literal["NEEDS_CONFIRMATION"]
    question: str
    options: list[str]
    reason_codes: list[str]


class PlanningSemanticRouteReconsiderationV1(TypedDict):
    disposition: Literal["ROUTE_RECONSIDERATION_REQUIRED"]
    reason_codes: list[str]


class PlanningSemanticBlockedV1(TypedDict):
    disposition: Literal["BLOCKED"]
    reason_codes: list[str]


PlanningSemanticControlV1 = (
    PlanningSemanticCompleteV1
    | PlanningSemanticNeedsConfirmationV1
    | PlanningSemanticRouteReconsiderationV1
    | PlanningSemanticBlockedV1
)


class PlanningAnswerCandidateProvider(Protocol):
    """Invocation-local semantic owner for ANSWER content only."""

    def draft_answer(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        work_analysis_result: WorkAnalysisResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
    ) -> object: ...


class PlanningV2RuntimeError(ValueError):
    pass


class PlanningV2Producer:
    def __init__(
        self,
        *,
        answer_candidate_provider: PlanningAnswerCandidateProvider,
        argument_orchestrator: PlanningArgumentOrchestratorV2,
        artifact_id_factory: Callable[[], str],
        action_id_factory: Callable[[], str],
    ) -> None:
        self._answer_candidate_provider = answer_candidate_provider
        self._argument_orchestrator = argument_orchestrator
        self._artifact_id_factory = artifact_id_factory
        self._action_id_factory = action_id_factory

    def run(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        tool_route_plan: ToolRoutePlanV2,
        retrieval_result: RetrievalResultV1,
        work_analysis_result: WorkAnalysisResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
        semantic_control: PlanningSemanticControlV1 | None = None,
        interrupt_id: str | None = None,
        resume_target: RegisteredResumeTargetRefV1 | None = None,
    ) -> SubgraphReturnV2[PlanningResultV2]:
        evidence = _validate_current_evidence(
            evidence_drafts,
            expected_refs=retrieval_result["evidence_refs"],
        )
        _validate_current_upstream(
            request_intent=request_intent,
            tool_route_plan=tool_route_plan,
            retrieval_result=retrieval_result,
            work_analysis_result=work_analysis_result,
        )
        control = validate_planning_semantic_control_v1(
            semantic_control or {"disposition": "COMPLETE"}
        )
        if control["disposition"] != "COMPLETE":
            return cast(
                SubgraphReturnV2[PlanningResultV2],
                _planning_control_return(
                    control,
                    interrupt_id=interrupt_id,
                    resume_target=resume_target,
                ),
            )

        meta = _planning_meta(
            artifact_id=_required_id(self._artifact_id_factory(), "planning artifact id"),
            tool_route_plan=tool_route_plan,
            work_analysis_result=work_analysis_result,
            retrieval_result=retrieval_result,
        )
        output_plan = tool_route_plan["output_plan"]
        if output_plan["output_mode"] == "ANSWER":
            candidate = validate_answer_draft_candidate_v2(
                self._answer_candidate_provider.draft_answer(
                    request=request,
                    request_intent=request_intent,
                    work_analysis_result=work_analysis_result,
                    evidence_drafts=evidence,
                ),
                allowed_evidence_refs=set(retrieval_result["evidence_refs"]),
            )
            answer = materialize_answer_draft_v2(
                cast(AnswerDraftCandidateV2, candidate),
                meta=meta,
                allowed_evidence_refs=set(retrieval_result["evidence_refs"]),
            )
            return cast(
                SubgraphReturnV2[PlanningResultV2],
                validate_planning_return_v2(
                    {
                        "disposition": "ANSWER_ONLY",
                        "typed_result": answer,
                        "workflow_signal": None,
                    }
                ),
            )

        routes = output_routes(tool_route_plan)
        preparations = self._argument_orchestrator.prepare_actions(output_routes=routes)
        nonready = _preparation_control_return(
            preparations,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )
        if nonready is not None:
            return cast(SubgraphReturnV2[PlanningResultV2], nonready)

        arguments = self._argument_orchestrator.compose_prepared(
            request=request,
            request_intent=request_intent,
            output_routes=routes,
            preparations=preparations,
            evidence_drafts=evidence,
            analysis_result=work_analysis_result,
        )
        seeds = materialize_action_seeds(
            output_routes=routes,
            argument_candidates=(result.candidate for result in arguments),
            action_id_factory=self._action_id_factory,
        )
        plan = assemble_action_plan_draft_v2(
            artifact_id=meta["artifact_id"],
            revision=meta["revision"],
            based_on=meta["based_on"],
            action_seeds=seeds,
        )
        return cast(
            SubgraphReturnV2[PlanningResultV2],
            validate_planning_return_v2(
                {
                    "disposition": "PLAN_READY",
                    "typed_result": plan,
                    "workflow_signal": None,
                }
            ),
        )


def validate_planning_semantic_control_v1(value: object) -> PlanningSemanticControlV1:
    if not isinstance(value, Mapping):
        raise PlanningV2RuntimeError("Planning semantic control must be an object")
    root = dict(value)
    disposition = root.get("disposition")
    if disposition == "COMPLETE":
        if set(root) != {"disposition"}:
            raise PlanningV2RuntimeError("COMPLETE planning control keys are invalid")
        return {"disposition": "COMPLETE"}
    if disposition == "NEEDS_CONFIRMATION":
        if set(root) != {"disposition", "question", "options", "reason_codes"}:
            raise PlanningV2RuntimeError("NEEDS_CONFIRMATION planning control keys are invalid")
        return {
            "disposition": "NEEDS_CONFIRMATION",
            "question": _text(root["question"], "question"),
            "options": _strings(root["options"], "options", allow_empty=True),
            "reason_codes": _strings(root["reason_codes"], "reason_codes"),
        }
    if disposition in {"ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"}:
        if set(root) != {"disposition", "reason_codes"}:
            raise PlanningV2RuntimeError("non-COMPLETE planning control keys are invalid")
        reasons = _strings(root["reason_codes"], "reason_codes")
        if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            return {"disposition": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": reasons}
        return {"disposition": "BLOCKED", "reason_codes": reasons}
    raise PlanningV2RuntimeError("Planning semantic control disposition is invalid")


def _planning_control_return(
    control: PlanningSemanticControlV1,
    *,
    interrupt_id: str | None,
    resume_target: RegisteredResumeTargetRefV1 | None,
) -> object:
    disposition = control["disposition"]
    if disposition == "NEEDS_CONFIRMATION":
        if interrupt_id is None or resume_target is None:
            raise PlanningV2RuntimeError(
                "Application-owned interrupt_id and resume_target are required for Planning confirmation"
            )
        preparation: PlanningActionPreparationResultV1 = {
            "disposition": "NEEDS_CONFIRMATION",
            "route_id": "planning-semantic",
            "question": control["question"],
            "options": list(control["options"]),
            "reason_codes": list(control["reason_codes"]),
        }
        signal = project_planning_action_confirmation_required_v1(
            preparation,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )
    elif disposition == "ROUTE_RECONSIDERATION_REQUIRED":
        signal = {
            "kind": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": list(control["reason_codes"]),
        }
    else:
        signal = {"kind": "BLOCKED", "reason_codes": list(control["reason_codes"])}
    return validate_planning_return_v2(
        {"disposition": disposition, "typed_result": None, "workflow_signal": signal}
    )


def _preparation_control_return(
    preparations: tuple[PlanningActionPreparationResultV1, ...],
    *,
    interrupt_id: str | None,
    resume_target: RegisteredResumeTargetRefV1 | None,
) -> object | None:
    blocked = [item for item in preparations if item["disposition"] == "BLOCKED"]
    if blocked:
        reasons = _ordered_unique(
            reason
            for item in blocked
            for reason in cast(Sequence[str], item["reason_codes"])
        )
        return validate_planning_return_v2(
            {
                "disposition": "BLOCKED",
                "typed_result": None,
                "workflow_signal": {"kind": "BLOCKED", "reason_codes": reasons},
            }
        )
    reconsider = [
        item for item in preparations if item["disposition"] == "ROUTE_RECONSIDERATION_REQUIRED"
    ]
    if reconsider:
        reasons = _ordered_unique(
            reason
            for item in reconsider
            for reason in cast(Sequence[str], item["reason_codes"])
        )
        return validate_planning_return_v2(
            {
                "disposition": "ROUTE_RECONSIDERATION_REQUIRED",
                "typed_result": None,
                "workflow_signal": {
                    "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                    "reason_codes": reasons,
                },
            }
        )
    confirmations = [item for item in preparations if item["disposition"] == "NEEDS_CONFIRMATION"]
    if confirmations:
        if interrupt_id is None or resume_target is None:
            raise PlanningV2RuntimeError(
                "Application-owned interrupt_id and resume_target are required for Planning confirmation"
            )
        signal = project_planning_action_confirmation_required_v1(
            confirmations[0],
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )
        return validate_planning_return_v2(
            {
                "disposition": "NEEDS_CONFIRMATION",
                "typed_result": None,
                "workflow_signal": signal,
            }
        )
    return None


def _validate_current_upstream(
    *,
    request_intent: RequestIntentV2,
    tool_route_plan: ToolRoutePlanV2,
    retrieval_result: RetrievalResultV1,
    work_analysis_result: WorkAnalysisResultV2,
) -> None:
    intent_ref = _artifact_ref(request_intent["meta"])
    output_meta = tool_route_plan["output_plan"]["meta"]
    if intent_ref not in output_meta["based_on"]:
        raise PlanningV2RuntimeError("stale Tool Route output artifact")
    input_ref = _artifact_ref(tool_route_plan["input_plan"]["meta"])
    if input_ref not in retrieval_result["meta"]["based_on"]:
        raise PlanningV2RuntimeError("stale RetrievalResultV1 for current Tool Route input artifact")
    retrieval_ref = _artifact_ref(retrieval_result["meta"])
    if retrieval_ref not in work_analysis_result["meta"]["based_on"]:
        raise PlanningV2RuntimeError("stale WorkAnalysisResultV2 for current RetrievalResultV1")


def _planning_meta(
    *,
    artifact_id: str,
    tool_route_plan: ToolRoutePlanV2,
    work_analysis_result: WorkAnalysisResultV2,
    retrieval_result: RetrievalResultV1,
) -> StateArtifactMetaV1:
    return {
        "artifact_id": artifact_id,
        "revision": 1,
        "based_on": [
            _artifact_ref(tool_route_plan["output_plan"]["meta"]),
            _artifact_ref(work_analysis_result["meta"]),
            _artifact_ref(retrieval_result["meta"]),
        ],
    }


def _artifact_ref(meta: Mapping[str, object]) -> StateArtifactRefV1:
    artifact_id = meta.get("artifact_id")
    revision = meta.get("revision")
    if not isinstance(artifact_id, str) or not artifact_id:
        raise PlanningV2RuntimeError("artifact meta id is invalid")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PlanningV2RuntimeError("artifact meta revision is invalid")
    return {"artifact_id": artifact_id, "revision": revision}


def _validate_current_evidence(
    evidence_drafts: Sequence[EvidenceDraftV1],
    *,
    expected_refs: Sequence[str],
) -> list[EvidenceDraftV1]:
    expected = list(expected_refs)
    if len(expected) != len(set(expected)):
        raise PlanningV2RuntimeError("RetrievalResultV1.evidence_refs contains duplicates")
    by_id: dict[str, EvidenceDraftV1] = {}
    for draft in evidence_drafts:
        evidence_id = draft["evidence_id"]
        if evidence_id in by_id:
            raise PlanningV2RuntimeError("duplicate current-run evidence id")
        by_id[evidence_id] = draft
    if set(by_id) != set(expected):
        raise PlanningV2RuntimeError("Planning evidence does not match current RetrievalResultV1")
    return [by_id[evidence_id] for evidence_id in expected]


def _required_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlanningV2RuntimeError(f"{label} is required")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PlanningV2RuntimeError(f"{field} must be non-empty")
    return value


def _strings(value: object, field: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PlanningV2RuntimeError(f"{field} must be a string array")
    result = list(value)
    if not allow_empty and not result:
        raise PlanningV2RuntimeError(f"{field} must not be empty")
    if len(result) != len(set(result)):
        raise PlanningV2RuntimeError(f"{field} contains duplicates")
    return cast(list[str], result)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = [
    "PlanningAnswerCandidateProvider",
    "PlanningSemanticControlV1",
    "PlanningV2Producer",
    "PlanningV2RuntimeError",
    "validate_planning_semantic_control_v1",
]
