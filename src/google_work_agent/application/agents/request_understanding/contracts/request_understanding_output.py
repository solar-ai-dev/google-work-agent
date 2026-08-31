"""Request Understanding result and clarification contracts."""

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)


class ClarificationOptionV1(TypedDict):
    option_id: str
    label: str


class ClarificationQuestionV1(TypedDict):
    schema_version: Required[Literal[1]]
    origin_target: str
    question: str
    affected_field_paths: list[str]
    reason_code: str
    known_context_summary: str
    options: list[ClarificationOptionV1]


class RequestUnderstandingFailureV1(TypedDict):
    schema_version: Required[Literal[1]]
    reason_code: str
    user_safe_message: str
    diagnostic: str


class RequestUnderstandingOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["COMPLETE", "NEEDS_CONFIRMATION", "INVALID"]
    request_intent: RequestIntentV2 | None
    clarification: ClarificationQuestionV1 | None
    failure: RequestUnderstandingFailureV1 | None
    validator_codes: list[str]
    llm_provider_result: NotRequired[dict[str, object]]
