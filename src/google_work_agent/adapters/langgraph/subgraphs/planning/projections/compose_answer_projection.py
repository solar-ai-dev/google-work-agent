"""Minimum current-Run projection for planning.compose_answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict, cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)


class ComposeAnswerInputV1(TypedDict):
    user_request: str
    request_intent: dict[str, object]
    answer_outline: AnswerOutlineV1
    evidence: list[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]
    retrieval_result: NotRequired[dict[str, object]]


def project_compose_answer_input(state: Mapping[str, object]) -> ComposeAnswerInputV1:
    user_request = state.get("user_request")
    request_intent = state.get("request_intent")
    answer_outline = state.get("answer_outline")
    evidence = state.get("evidence", ())
    work_analysis = state.get("work_analysis", state.get("work_analysis_result"))
    confirmation_response = state.get("confirmation_response")
    retrieval_result = state.get("retrieval_result")
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("user_request is required")
    if not isinstance(request_intent, Mapping):
        raise ValueError("request_intent is required")
    if not isinstance(answer_outline, Mapping):
        raise ValueError("answer_outline is required")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    if not all(isinstance(item, Mapping) for item in evidence):
        raise ValueError("evidence items must be objects")
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        raise ValueError("work_analysis must be an object")
    if confirmation_response is not None and not isinstance(confirmation_response, Mapping):
        raise ValueError("confirmation_response must be an object")
    if retrieval_result is not None and not isinstance(retrieval_result, Mapping):
        raise ValueError("retrieval_result must be an object")
    result: ComposeAnswerInputV1 = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "answer_outline": cast(AnswerOutlineV1, dict(answer_outline)),
        "evidence": [dict(item) for item in evidence],
    }
    if work_analysis is not None:
        result["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        result["confirmation_response"] = dict(confirmation_response)
    if retrieval_result is not None:
        result["retrieval_result"] = dict(retrieval_result)
    return result


__all__ = ["ComposeAnswerInputV1", "project_compose_answer_input"]
