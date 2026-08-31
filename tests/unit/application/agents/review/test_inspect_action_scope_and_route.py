from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)

DIMENSION = "review.inspect_action_scope_and_route"


def _result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "dimension": DIMENSION,
        "findings": [
            {
                "dimension": DIMENSION,
                "code": "SCOPE_EXPANSION",
                "finding_kind": "ROUTE_ISSUE",
                "description": "The action exceeds the frozen route.",
                "evidence_refs": [],
                "affected_action_ids": ["action-1"],
                "affected_route_ids": ["route-1"],
                "required_information": [],
            }
        ],
    }


def test_inspect_action_scope_and_route_reads_frozen_route_without_mutating_it() -> None:
    route = {"output_plan": {"output_routes": [{"route_id": "route-1"}]}}
    original = {"output_plan": {"output_routes": [{"route_id": "route-1"}]}}
    calls: list[dict[str, object]] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        assert prompt_id == DIMENSION
        calls.append(dict(prompt_input))
        return _result()

    result = inspect_action_scope_and_route(
        request_intent={"goal": "create"},
        tool_route_plan=route,
        planning_result={"schema_version": 2, "actions": [{"action_id": "action-1"}]},
        evidence=[],
        invoke=invoke,
    )

    assert result["findings"][0]["affected_route_ids"] == ["route-1"]
    assert set(calls[0]) == {
        "request_intent",
        "tool_route_plan",
        "planning_result",
        "evidence",
    }
    assert route == original


def test_inspect_action_scope_and_route_rejects_free_form_finding_shape() -> None:
    candidate = _result()
    candidate["findings"] = [{"dimension": DIMENSION, "code": "x"}]
    with pytest.raises(ValueError, match="finding keys"):
        inspect_action_scope_and_route(
            request_intent={},
            tool_route_plan={},
            planning_result={"actions": []},
            evidence=[],
            invoke=lambda _prompt_id, _input: candidate,
        )
