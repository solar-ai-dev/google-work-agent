"""Canonical Planning result union."""

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.planning.contracts.answer_draft import (
    AnswerDraftV2,
)

PlanningResultV2 = AnswerDraftV2 | ActionPlanDraftV2

__all__ = ["PlanningResultV2"]
