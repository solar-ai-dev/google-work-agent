from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)

DIMENSION = "review.inspect_constraints_and_policy_summary"


def _result() -> dict[str, object]:
    return {"schema_version": 1, "dimension": DIMENSION, "findings": []}


def test_inspect_constraints__uses_only_bounded__supplied_policy_summary() -> None:
    calls: list[dict[str, object]] = []
    policy_summary = {"tool_policies": [{"tool_id": "calendar.create_event"}]}

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == DIMENSION
        calls.append(dict(prompt_input))
        return _result()

    result = inspect_constraints_and_policy_summary(
        request_intent={"constraints": [{"field": "time", "value": "09:00"}]},
        planning_result={"schema_version": 2, "actions": []},
        policy_summary=policy_summary,
        evidence=[],
        invoke=invoke,
    )

    assert result == _result()
    assert set(calls[0]) == {"request_intent", "planning_result", "policy_summary"}
    assert calls[0]["policy_summary"] == policy_summary
    assert "tool_route_plan" not in calls[0]


def test_inspect_constraints_skips__inference_when_bounded__inputs_are_empty() -> None:
    result = inspect_constraints_and_policy_summary(
        request_intent={"constraints": []},
        planning_result={"schema_version": 2, "actions": []},
        policy_summary={},
        invoke=lambda _prompt_id, _input: pytest.fail("empty inputs must not invoke the LLM"),
    )

    assert result == _result()


def test_inspect_constraints__rejects_finding__with_final_status() -> None:
    candidate = _result()
    candidate["status"] = "BLOCK"
    with pytest.raises(ValueError, match="keys do not match"):
        inspect_constraints_and_policy_summary(
            request_intent={},
            planning_result={},
            policy_summary={},
            invoke=lambda _prompt_id, _input: candidate,
        )
