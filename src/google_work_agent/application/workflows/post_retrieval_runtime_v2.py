"""Checkpoint-B coherent post-Retrieval V2 application boundary.

Main State and Main Supervisor remain unchanged until Checkpoint C.  This
boundary nevertheless makes the V2 producer/caller chain concrete and gives
CanonicalDomainValidationService an actual downstream caller using only V2
Planning/Review artifacts.
"""

from __future__ import annotations

from collections.abc import Sequence

from google_work_agent.application.workflows.contracts import (
    DomainValidationOutputV1,
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.workflows.domain_validation_v2 import (
    CanonicalDomainValidationService,
    RunScopedResourceIdentityReader,
)
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RegisteredResumeTargetRefV1,
    RequestIntentV2,
    RetrievalResultV1,
    SubgraphReturnV2,
)
from google_work_agent.application.workflows.planning_plan_assembler import ActionPlanDraftV2
from google_work_agent.application.workflows.planning_runtime_v2 import (
    PlanningResultV2,
    PlanningSemanticControlV1,
    PlanningV2Producer,
)
from google_work_agent.application.workflows.review_runtime_v2 import ReviewV2Producer
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.ports import WorkflowStartRequest


class PostRetrievalRuntimeV2Boundary:
    """Application caller chain prepared for the atomic LangGraph cut-over."""

    def __init__(
        self,
        *,
        planning: PlanningV2Producer,
        review: ReviewV2Producer,
        domain_validation: CanonicalDomainValidationService,
    ) -> None:
        self._planning = planning
        self._review = review
        self._domain_validation = domain_validation

    def plan(
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
        return self._planning.run(
            request=request,
            request_intent=request_intent,
            tool_route_plan=tool_route_plan,
            retrieval_result=retrieval_result,
            work_analysis_result=work_analysis_result,
            evidence_drafts=evidence_drafts,
            semantic_control=semantic_control,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )

    def review(
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
        return self._review.run(
            request_intent=request_intent,
            retrieval_result=retrieval_result,
            work_analysis_result=work_analysis_result,
            planning_result=planning_result,
            evidence_drafts=evidence_drafts,
            interrupt_id=interrupt_id,
            resume_target=resume_target,
        )

    def domain_validate(
        self,
        *,
        run_id: str,
        planning_result: ActionPlanDraftV2,
        plan_review: PlanReviewResultV2,
        work_analysis_result: WorkAnalysisResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
        policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1],
        resource_identity_reader: RunScopedResourceIdentityReader,
    ) -> DomainValidationOutputV1:
        """Actual Checkpoint-B caller of CanonicalDomainValidationService."""

        return self._domain_validation(
            run_id=run_id,
            planning_result=planning_result,
            plan_review=plan_review,
            work_analysis_result=work_analysis_result,
            evidence_drafts=evidence_drafts,
            policy_confirmation_receipts=policy_confirmation_receipts,
            resource_identity_reader=resource_identity_reader,
        )


__all__ = ["PostRetrievalRuntimeV2Boundary"]
