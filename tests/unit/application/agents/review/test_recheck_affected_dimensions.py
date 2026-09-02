from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.application.agents.review.recheck_affected_dimensions import (
    recheck_affected_dimensions,
)


def test_recheck_affected_dimensions__uses_one_prompt__and_bounded_selector() -> None:
    calls: list[tuple[str, Mapping[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append((prompt_id, prompt_input))
        return {
            "schema_version": 1,
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "findings": [],
        }

    result = recheck_affected_dimensions(
        affected_dimensions=["review.inspect_action_scope_and_route"],
        affected_action_ids=["a1"],
        affected_route_ids=["r1"],
        request_intent={"goal": "update task"},
        tool_route_plan={"route_id": "r1"},
        planning_result={"actions": [{"action_id": "a1"}]},
        evidence=[],
        invoke=invoke,
    )

    assert result["affected_dimensions"] == ("review.inspect_action_scope_and_route",)
    assert [prompt_id for prompt_id, _ in calls] == ["review.recheck_affected_dimensions"]
    prompt_input = calls[0][1]
    assert "prior_review_findings" not in prompt_input
    assert "full_plan" not in prompt_input
