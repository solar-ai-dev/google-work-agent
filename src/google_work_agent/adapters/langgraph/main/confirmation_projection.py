"""Shared deterministic confirmation projections for agent subgraphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_result import (
    ActionPlanDraftV1,
    AnswerDraftV1,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
    UserInterruptV1,
    validate_confirmation_origin_target,
    validate_confirmation_response_projection_v1,
    validate_user_interrupt_v1,
)


def validate_clarification_question_v1(
    value: object,
) -> request_understanding_output.ClarificationQuestionV1:
    if not isinstance(value, Mapping):
        raise ValueError("clarification question must be an object")
    expected = {
        "schema_version",
        "origin_target",
        "question",
        "affected_field_paths",
        "reason_code",
        "known_context_summary",
        "options",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise ValueError("clarification question fields are invalid")
    options_raw = value.get("options")
    if not isinstance(options_raw, list):
        raise ValueError("clarification options must be a list")
    options: list[request_understanding_output.ClarificationOptionV1] = []
    option_ids: set[str] = set()
    for item in options_raw:
        if not isinstance(item, Mapping) or set(item) != {"option_id", "label"}:
            raise ValueError("clarification option fields are invalid")
        option_id, label = item.get("option_id"), item.get("label")
        if (
            not isinstance(option_id, str)
            or not option_id
            or option_id in option_ids
            or not isinstance(label, str)
            or not label
        ):
            raise ValueError("clarification option is invalid")
        option_ids.add(option_id)
        options.append({"option_id": option_id, "label": label})
    affected = value.get("affected_field_paths")
    if not isinstance(affected, list) or any(not isinstance(item, str) for item in affected):
        raise ValueError("affected_field_paths must contain strings")
    question = value.get("question")
    reason_code = value.get("reason_code")
    summary = value.get("known_context_summary")
    if any(not isinstance(item, str) or not item for item in (question, reason_code, summary)):
        raise ValueError("clarification text fields must be non-empty strings")
    return {
        "schema_version": 1,
        "origin_target": validate_confirmation_origin_target(value.get("origin_target")),
        "question": cast(str, question),
        "affected_field_paths": cast(list[str], affected),
        "reason_code": cast(str, reason_code),
        "known_context_summary": cast(str, summary),
        "options": options,
    }


def build_clarification_question_v1(
    *,
    origin_target: str,
    question: str,
    reason_code: str,
    known_context_summary: str,
    affected_field_paths: list[str] | None = None,
    options: list[dict[str, object]] | None = None,
) -> request_understanding_output.ClarificationQuestionV1:
    return validate_clarification_question_v1(
        {
            "schema_version": 1,
            "origin_target": origin_target,
            "question": question,
            "affected_field_paths": list(affected_field_paths or []),
            "reason_code": reason_code,
            "known_context_summary": known_context_summary,
            "options": list(options or []),
        }
    )


def build_solution_planning_clarification_question(
    *,
    result: AnswerDraftV1 | ActionPlanDraftV1,
    request_intent: RequestIntentV2,
) -> request_understanding_output.ClarificationQuestionV1:
    confirmation = result.get("confirmation")
    if not isinstance(confirmation, Mapping):
        raise ValueError("planning confirmation must be an object")
    question = confirmation.get("question")
    reason_code = confirmation.get("reason_code")
    affected = confirmation.get("affected_field_paths", [])
    options = confirmation.get("options", [])
    if not isinstance(question, str) or not isinstance(reason_code, str):
        raise ValueError("planning confirmation text is invalid")
    if not isinstance(affected, list) or not isinstance(options, list):
        raise ValueError("planning confirmation collections are invalid")
    return build_clarification_question_v1(
        origin_target=(
            "planning.outline_answer"
            if "answer" in result
            else "planning.compose_arguments_per_output_route"
        ),
        question=question,
        reason_code=reason_code,
        known_context_summary=request_intent["goal"],
        affected_field_paths=cast(list[str], affected),
        options=cast(list[dict[str, object]], options),
    )


def build_user_interrupt_v1(
    question: request_understanding_output.ClarificationQuestionV1,
) -> UserInterruptV1:
    normalized = validate_clarification_question_v1(question)
    return validate_user_interrupt_v1(
        {
            "schema_version": 1,
            "interrupt_kind": "CONFIRMATION",
            "resume_kind": "CONFIRMATION",
            "origin_target": normalized["origin_target"],
            "question": normalized["question"],
            "affected_field_paths": list(normalized["affected_field_paths"]),
            "reason_code": normalized["reason_code"],
            "known_context_summary": normalized["known_context_summary"],
            "options": [dict(option) for option in normalized["options"]],
        }
    )


def resolve_confirmation_origin_target(
    *,
    user_interrupt: UserInterruptV1,
    response: ConfirmationResponseProjectionV1,
) -> str:
    question = validate_user_interrupt_v1(user_interrupt)
    normalized = validate_confirmation_response_projection_v1(response)
    if normalized["response_kind"] == "OPTION":
        allowed_ids = {option["option_id"] for option in question["options"]}
        if normalized["selected_option"] not in allowed_ids:
            raise ValueError("unknown clarification option_id")
    return question["origin_target"]
