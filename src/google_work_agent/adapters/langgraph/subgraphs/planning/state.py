"""Canonical semantic state owned by Planning."""

from __future__ import annotations

from typing import TypedDict

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    AnswerDraftCandidateV2,
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputPlanV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAnalysisResultV2,
)


class PlanningStateV2(TypedDict, total=False):
    user_request: str
    request_intent: RequestIntentV2
    output_plan: OutputPlanV1
    work_analysis: WorkAnalysisResultV2
    evidence_refs: list[str]
    action_objective_candidates: list[ActionObjectiveCandidateV1]
    argument_candidates: list[ToolArgumentCandidateV1]
    dependency_candidates: list[ActionDependencyCandidateV1]
    final_result: AnswerDraftCandidateV2 | ActionPlanDraftV2


__all__ = ["PlanningStateV2"]
