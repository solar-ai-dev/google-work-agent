"""Single deterministic dispatch authority for Main workflow routing."""

from __future__ import annotations

from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    artifact_freshness_violation,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    base_supervisor_state_update,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_execution_rules import (
    route_domain_validation,
    route_preflight,
)
from google_work_agent.adapters.langgraph.main.supervisor_intake_rules import (
    route_initialize,
    route_reconsideration,
    route_request_understanding,
    route_tool_routing,
)
from google_work_agent.adapters.langgraph.main.supervisor_planning_rules import (
    route_plan_review,
    route_planning,
    route_work_analysis,
)
from google_work_agent.adapters.langgraph.main.supervisor_result_contracts import (
    PlanningRouteResultV1,
    RetrievalRouteResultV1,
    WorkAnalysisRouteResultV1,
)
from google_work_agent.adapters.langgraph.main.supervisor_retrieval_rules import (
    route_retrieval,
)
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    claim_result_mapping,
    require_mapping,
)
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationOutputV1,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRouteResultV1,
)


def route_supervisor(
    *,
    phase: WorkflowPhase | str,
    state: GraphState,
    result: object | None = None,
) -> SupervisorDecisionV1:
    """Evaluate one typed phase result without persistence or domain mutation."""

    current_phase = WorkflowPhase(phase)
    if current_phase is WorkflowPhase.INITIALIZE:
        return route_initialize(require_mapping(result, "result"))
    freshness_reason = artifact_freshness_violation(current_phase, state)
    if freshness_reason is not None:
        return make_supervisor_decision(
            target=SupervisorTarget.RECOVERY,
            next_phase=WorkflowPhase.RECOVERY,
            state_update=base_supervisor_state_update(WorkflowPhase.RECOVERY),
            reason_code=freshness_reason,
        )
    reconsideration = route_reconsideration(current_phase, result)
    if reconsideration is not None:
        return reconsideration
    if current_phase is WorkflowPhase.REQUEST_ANALYSIS:
        return route_request_understanding(
            state=state,
            output=cast(
                request_understanding_output.RequestUnderstandingOutputV1,
                require_mapping(result, "result"),
            ),
        )
    if current_phase is WorkflowPhase.TOOL_ROUTING:
        return route_tool_routing(
            state=state,
            result=cast(ToolRouteResultV1, require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.CONTEXT_RETRIEVAL:
        return route_retrieval(
            state=state,
            retrieval_return=cast(
                RetrievalRouteResultV1,
                require_mapping(result, "result"),
            ),
        )
    if current_phase is WorkflowPhase.WORK_ANALYSIS:
        return route_work_analysis(
            state=state,
            result=cast(WorkAnalysisRouteResultV1, require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.SOLUTION_PLANNING:
        return route_planning(
            state=state,
            result=cast(PlanningRouteResultV1, require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.PLAN_REVIEW:
        return route_plan_review(
            state=state,
            result=cast(PlanReviewResultV2, require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.DOMAIN_VALIDATION:
        return route_domain_validation(
            state=state,
            result=cast(DomainValidationOutputV1, require_mapping(result, "result")),
        )
    if current_phase is WorkflowPhase.PREFLIGHT:
        return route_preflight(
            state=state,
            result=claim_result_mapping(result, "result"),
        )
    if current_phase is WorkflowPhase.RECOVERY:
        return make_supervisor_decision(
            target=SupervisorTarget.RECOVERY,
            next_phase=WorkflowPhase.RECOVERY,
            state_update=base_supervisor_state_update(WorkflowPhase.RECOVERY),
            reason_code="RECOVERY_REQUIRED",
        )
    if current_phase is WorkflowPhase.FINALIZE:
        return make_supervisor_decision(
            target=SupervisorTarget.FINALIZE,
            next_phase=WorkflowPhase.FINALIZE,
            state_update=base_supervisor_state_update(WorkflowPhase.FINALIZE),
            reason_code="FINALIZE_READY",
        )
    raise ValueError(f"unsupported supervisor phase: {current_phase.value}")


__all__ = [
    "PlanningRouteResultV1",
    "RetrievalRouteResultV1",
    "WorkAnalysisRouteResultV1",
    "route_supervisor",
]
