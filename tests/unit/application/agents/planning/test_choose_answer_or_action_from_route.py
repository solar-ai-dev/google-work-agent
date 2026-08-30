from __future__ import annotations

from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)


def test_chooses_only_from_frozen_output_mode() -> None:
    answer = {"output_plan": {"output_mode": "ANSWER", "output_routes": []}}
    action = {"output_plan": {"output_mode": "ACTION", "output_routes": [{}]}}

    assert choose_answer_or_action_from_route(answer) == "ANSWER"
    assert choose_answer_or_action_from_route(action) == "ACTION"


def test_rejects_missing_frozen_output_mode() -> None:
    import pytest

    with pytest.raises(ValueError):
        choose_answer_or_action_from_route({"output_plan": {}})
