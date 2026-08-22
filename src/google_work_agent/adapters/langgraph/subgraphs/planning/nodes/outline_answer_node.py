"""Thin adapter for planning.outline_answer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer


def outline_answer_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_planning_input(state)
    request_intent = projected.get("request_intent")
    evidence = projected.get("evidence", ())
    work_analysis = projected.get("work_analysis")
    if not isinstance(request_intent, Mapping):
        raise ValueError("request_intent is required")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        raise ValueError("work_analysis must be an object")
    return {
        "answer_outline": outline_answer(
            request_intent=request_intent,
            work_analysis=work_analysis,
            evidence=evidence,  # type: ignore[arg-type]
        )
    }
