"""Owner-local V1 Planning artifacts used at the bounded legacy seam."""

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)
from google_work_agent.application.agents.planning.contracts.answer_draft import (
    AnswerDraftV2,
)

PlanningResultV2 = AnswerDraftV2 | ActionPlanDraftV2


AnswerDraftStatusValue = Literal[
    "ANSWER_ONLY", "NEEDS_CONFIRMATION", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"
]


PlanDraftStatusValue = Literal[
    "PLAN_READY", "NEEDS_CONFIRMATION", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"
]


ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]


class AnswerDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: AnswerDraftStatusValue
    answer: str
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    reason_codes: list[str]
    confirmation: dict[str, object] | None
    blockers: list[str]
    llm_provider_result: NotRequired[dict[str, object]]


class ActionDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    action_id: str
    position: int
    effect: ActionEffectValue
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_refs: list[str]
    resource_refs: list[str]
    target_resource_ref_id: str | None
    depends_on_action_ids: list[str]
    user_visible_reason: str


class ActionPlanDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: PlanDraftStatusValue
    plan_id: str
    summary: str
    objective: str
    actions: list[ActionDraftV1]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    confirmation: dict[str, object] | None
    llm_provider_result: NotRequired[dict[str, object]]
