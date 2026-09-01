"""Shared deterministic confirmation projections for agent subgraphs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.ports.system.contracts.confirmation import (
    UserInterruptV1,
    validate_confirmation_origin_target,
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
