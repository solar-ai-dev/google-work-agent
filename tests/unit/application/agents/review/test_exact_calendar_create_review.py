from collections.abc import Mapping

from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)


def test_exact_calendar_create__skips_no_information__review_inference() -> None:
    request_intent, planning_result, tool_route_plan = _exact_calendar_state()

    def fail_inference(_prompt_id: str, _input: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("an exact deterministic plan adds no Review LLM information")

    results = (
        inspect_goal_and_evidence(
            request_intent=request_intent,
            planning_result=planning_result,
            evidence=[],
            invoke=fail_inference,
        ),
        inspect_action_scope_and_route(
            request_intent=request_intent,
            tool_route_plan=tool_route_plan,
            planning_result=planning_result,
            evidence=[],
            invoke=fail_inference,
        ),
        inspect_constraints_and_policy_summary(
            request_intent=request_intent,
            planning_result=planning_result,
            policy_summary={},
            invoke=fail_inference,
        ),
    )

    assert [result["findings"] for result in results] == [[], [], []]


def test_exact_calendar_create__keeps_review__for_extra_unchecked_scope() -> None:
    request_intent, planning_result, _tool_route_plan = _exact_calendar_state()
    request_intent["constraints"].append(
        {"kind": "EMAIL", "field": "attendee", "value": "person@example.com"}
    )
    calls: list[str] = []

    inspect_goal_and_evidence(
        request_intent=request_intent,
        planning_result=planning_result,
        evidence=[],
        invoke=lambda prompt_id, _input: calls.append(prompt_id)
        or {
            "schema_version": 1,
            "dimension": "review.inspect_goal_and_evidence",
            "findings": [],
        },
    )

    assert calls == ["review.inspect_goal_and_evidence"]


def _exact_calendar_state() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    route_id = "route-calendar"
    request_intent: dict[str, object] = {
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "requested_effect_hints": ["CREATE"],
        "ambiguity": {"requires_confirmation": False},
        "constraints": [
            {"kind": "RESOURCE", "field": "title", "value": "[GWA OPT] Calendar"},
            {"kind": "DATE", "field": "date", "value": "2026-09-12"},
            {"kind": "TIME", "field": "start_time", "value": "15:00"},
            {"kind": "TIME", "field": "end_time", "value": "15:30"},
            {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
        ],
    }
    planning_result: dict[str, object] = {
        "schema_version": 2,
        "actions": [
            {
                "action_id": "action-calendar",
                "route_id": route_id,
                "tool_id": "calendar_create_event",
                "effect": "CREATE",
                "arguments": {
                    "calendar_id": "primary",
                    "payload": {
                        "title": "[GWA OPT] Calendar",
                        "start": "2026-09-12T15:00:00+09:00",
                        "end": "2026-09-12T15:30:00+09:00",
                    },
                },
            }
        ],
    }
    tool_route_plan: dict[str, object] = {
        "output_plan": {
            "output_mode": "ACTION",
            "output_routes": [
                {
                    "route_id": route_id,
                    "resource_type": "CALENDAR_EVENT",
                    "connector_id": "google_workspace",
                    "effect": "CREATE",
                    "selected_tool_id": "calendar_create_event",
                }
            ],
        }
    }
    return request_intent, planning_result, tool_route_plan
