"""Minimum current-Run projection for planning.compose_answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def project_compose_answer_input(state: Mapping[str, object]) -> dict[str, object]:
    user_request = state.get("user_request")
    request_intent = state.get("request_intent")
    answer_outline = state.get("answer_outline")
    evidence = state.get("evidence", ())
    work_analysis = state.get("work_analysis", state.get("work_analysis_result"))
    confirmation_response = state.get("confirmation_response")
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
    result: dict[str, object] = {
        "user_request": user_request,
        "request_intent": dict(request_intent),
        "answer_outline": dict(answer_outline),
        "evidence": [dict(item) for item in evidence],
    }
    if work_analysis is not None:
        result["work_analysis"] = dict(work_analysis)
    if confirmation_response is not None:
        result["confirmation_response"] = dict(confirmation_response)
    return result


__all__ = ["project_compose_answer_input"]
