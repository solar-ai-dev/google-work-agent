from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.compose_answer_node import (
    compose_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    compose_answer_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_compose_answer as compose_answer_routing,
)


def test_compose_exact__node_projection__and_router() -> None:
    assert callable(compose_answer_node)
    projected = compose_answer_projection.project_compose_answer_input(
        {
            "user_request": "Summarize.",
            "request_intent": {"goal": "summary"},
            "answer_outline": {"sections": ["Conclusion"], "evidence_refs": []},
            "evidence": [],
            "provider_response": {"raw": True},
            "previous_run": {"answer": "old"},
        }
    )
    assert set(projected) == {
        "user_request",
        "request_intent",
        "answer_outline",
        "evidence",
    }
    assert compose_answer_routing.route_after_compose_answer({"answer_draft": {}}) == "end"


def test_outline_and__compose_prompt_inputs__are_not_interchangeable() -> None:
    outline = {"user_request", "request_intent", "evidence"}
    compose = set(
        compose_answer_projection.project_compose_answer_input(
            {
                "user_request": "Summarize.",
                "request_intent": {"goal": "summary"},
                "answer_outline": {"sections": ["Conclusion"], "evidence_refs": []},
                "evidence": [],
            }
        )
    )
    assert outline != compose
    assert "answer_outline" in compose
