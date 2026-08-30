from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)

DIMENSION = "review.inspect_goal_and_evidence"


def _result(*, dimension: str = DIMENSION) -> dict[str, object]:
    return {
        "schema_version": 1,
        "dimension": dimension,
        "findings": [
            {
                "dimension": dimension,
                "code": "UNSUPPORTED_CLAIM",
                "finding_kind": "ISSUE",
                "description": "The conclusion is not grounded.",
                "evidence_refs": ["ev-1"],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "required_information": [],
            }
        ],
    }


def test_inspect_goal_and_evidence_uses_only_its_minimum_projection() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def invoke(prompt_id: str, prompt_input: dict[str, object]) -> dict[str, object]:
        calls.append((prompt_id, prompt_input))
        return _result()

    result = inspect_goal_and_evidence(
        request_intent={"goal": "answer"},
        planning_result={"schema_version": 2, "answer": "draft"},
        evidence=[{"evidence_ref": "ev-1"}],
        work_analysis={"facts": []},
        invoke=invoke,
    )

    assert result["dimension"] == DIMENSION
    assert set(calls[0][1]) == {
        "request_intent",
        "planning_result",
        "evidence",
        "work_analysis",
    }
    assert "status" not in result


@pytest.mark.parametrize("dimension", ["GOAL_EVIDENCE", "review.unknown"])
def test_inspect_goal_and_evidence_rejects_noncanonical_dimension(dimension: str) -> None:
    with pytest.raises(ValueError, match="invalid dimension"):
        inspect_goal_and_evidence(
            request_intent={},
            planning_result={},
            evidence=[],
            invoke=lambda _prompt_id, _input: _result(dimension=dimension),
        )


def test_inspect_goal_and_evidence_rejects_final_disposition_field() -> None:
    candidate = _result()
    candidate["status"] = "REVISE"
    with pytest.raises(ValueError, match="keys do not match"):
        inspect_goal_and_evidence(
            request_intent={},
            planning_result={},
            evidence=[],
            invoke=lambda _prompt_id, _input: candidate,
        )
