import pytest

from google_work_agent.application.agents.planning.validate_plan import validate_plan


def _plan() -> dict[str, object]:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "p", "revision": 1, "based_on": []},
        "actions": [
            {
                "action_id": "a",
                "route_id": "r",
                "tool_id": "gmail_send",
                "effect": "SEND",
                "arguments": {"draft_id": "d"},
                "evidence_refs": ["e1"],
                "depends_on_action_ids": [],
            }
        ],
    }


def test_validate_plan_preserves__frozen_route_tool__effect_and_evidence() -> None:
    route = {"route_id": "r", "selected_tool_id": "gmail_send", "effect": "SEND"}
    assert (
        validate_plan(_plan(), output_routes=[route], allowed_evidence_refs={"e1"})["actions"][0][
            "tool_id"
        ]
        == "gmail_send"
    )
    broken = _plan()
    broken["actions"][0]["tool_id"] = "gmail_create_draft"  # type: ignore[index]
    with pytest.raises(ValueError, match="frozen"):
        validate_plan(broken, output_routes=[route], allowed_evidence_refs={"e1"})
