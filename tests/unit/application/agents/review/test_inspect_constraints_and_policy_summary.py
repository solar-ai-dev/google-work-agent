from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)

DIMENSION = "review.inspect_constraints_and_policy_summary"


def _result() -> dict[str, object]:
    return {"schema_version": 1, "dimension": DIMENSION, "findings": []}


def test_inspect_constraints_uses_only_bounded_supplied_policy_summary() -> None:
    calls: list[dict[str, object]] = []
    policy_summary = {"tool_policies": [{"tool_id": "calendar.create_event"}]}

    result = inspect_constraints_and_policy_summary(
        request_intent={"constraints": [{"field": "time", "value": "09:00"}]},
        planning_result={"schema_version": 2, "actions": []},
        policy_summary=policy_summary,
        evidence=[],
        invoke=lambda _prompt_id, prompt_input: calls.append(prompt_input) or _result(),
    )

    assert result == _result()
    assert set(calls[0]) == {"request_intent", "planning_result", "policy_summary"}
    assert calls[0]["policy_summary"] == policy_summary
    assert "tool_route_plan" not in calls[0]


def test_inspect_constraints_rejects_finding_with_final_status() -> None:
    candidate = _result()
    candidate["status"] = "BLOCK"
    with pytest.raises(ValueError, match="keys do not match"):
        inspect_constraints_and_policy_summary(
            request_intent={},
            planning_result={},
            policy_summary={},
            invoke=lambda _prompt_id, _input: candidate,
        )
