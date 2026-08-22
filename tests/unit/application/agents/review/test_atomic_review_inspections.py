from __future__ import annotations

from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)


def test_three_review_dimensions_use_three_distinct_prompt_ids() -> None:
    calls: list[str] = []
    def invoke(prompt_id: str, _input: dict[str, object]) -> dict[str, object]:
        calls.append(prompt_id)
        return {"findings": []}
    kwargs = dict(
        request_intent={},
        tool_route_plan={},
        planning_result={},
        evidence=[],
        work_analysis=None,
        policy_summary=None,
        invoke=invoke,
    )
    inspect_goal_and_evidence(**kwargs)
    inspect_action_scope_and_route(**kwargs)
    inspect_constraints_and_policy_summary(**kwargs)
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
        "review.inspect_constraints_and_policy_summary",
    ]
    assert "review.inspect" not in calls
