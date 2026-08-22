from __future__ import annotations

import pytest

from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)
from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    draft_action_objective_per_output_route,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer


def test_choose_answer_or_action_uses_frozen_route() -> None:
    assert choose_answer_or_action_from_route({"output_plan": {"output_mode": "ACTION"}}) == "ACTION"
    assert choose_answer_or_action_from_route({"output_plan": {"output_mode": "ANSWER"}}) == "ANSWER"


def test_compose_answer_cannot_escape_outline_evidence() -> None:
    outline = outline_answer(request_intent={"goal": "g"}, work_analysis=None, evidence=[{"id": "e1"}])
    with pytest.raises(ValueError, match="outside"):
        compose_answer(
            user_request="answer",
            request_intent={"goal": "g"},
            answer_outline=outline,
            work_analysis=None,
            evidence=[{"id": "e1"}],
            invoke=lambda _id, _input: {"answer": "x", "evidence_refs": ["e2"]},
        )


def test_objective_is_called_once_per_frozen_route() -> None:
    calls: list[str] = []
    def invoke(_id: str, data: dict[str, object]) -> dict[str, object]:
        route = data["output_route"]
        assert isinstance(route, dict)
        calls.append(route["route_id"])
        return {"route_id": route["route_id"], "objective": "do it", "evidence_refs": []}
    result = draft_action_objective_per_output_route(
        [{"route_id": "r1"}, {"route_id": "r2"}],
        user_request="do",
        request_intent={},
        work_analysis=None,
        evidence=[],
        invoke=invoke,
    )
    assert [item["route_id"] for item in result] == ["r1", "r2"]
    assert calls == ["r1", "r2"]
