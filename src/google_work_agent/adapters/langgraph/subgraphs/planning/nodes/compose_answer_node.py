"""Thin adapter for planning.compose_answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)


def compose_answer_node(
    state: Mapping[str, object], *, invoke: PlanningSemanticInvoker
) -> dict[str, object]:
    projected = project_planning_input(state)
    user_request = projected.get("user_request")
    request_intent = projected.get("request_intent")
    answer_outline = projected.get("answer_outline")
    work_analysis = projected.get("work_analysis_result")
    evidence = projected.get("evidence", ())
    confirmation_response = projected.get("confirmation_response")
    if not isinstance(user_request, str):
        raise ValueError("user_request is required")
    if not isinstance(request_intent, Mapping) or not isinstance(answer_outline, Mapping):
        raise ValueError("request_intent and answer_outline are required")
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        raise ValueError("work_analysis_result must be an object")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    if confirmation_response is not None and not isinstance(confirmation_response, Mapping):
        raise ValueError("confirmation_response must be an object")
    return {
        "answer_draft": compose_answer(
            user_request=user_request,
            request_intent=request_intent,
            answer_outline=answer_outline,  # type: ignore[arg-type]
            work_analysis=work_analysis,
            evidence=evidence,  # type: ignore[arg-type]
            invoke=invoke,
            confirmation_response=confirmation_response,
        )
    }
