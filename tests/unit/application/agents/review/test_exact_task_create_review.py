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


def test_exact_task_create__skips_no_information__review_inference() -> None:
    request_intent, planning_result, tool_route_plan, work_analysis = _exact_task_state()

    def fail_inference(_prompt_id: str, _input: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError("an exact task plan with clean duplicate analysis adds no information")

    results = (
        inspect_goal_and_evidence(
            request_intent=request_intent,
            planning_result=planning_result,
            evidence=[],
            work_analysis=work_analysis,
            invoke=fail_inference,
        ),
        inspect_action_scope_and_route(
            request_intent=request_intent,
            tool_route_plan=tool_route_plan,
            planning_result=planning_result,
            evidence=[],
            work_analysis=work_analysis,
            invoke=fail_inference,
        ),
        inspect_constraints_and_policy_summary(
            request_intent=request_intent,
            planning_result=planning_result,
            policy_summary={},
            work_analysis=work_analysis,
            invoke=fail_inference,
        ),
    )

    assert [result["findings"] for result in results] == [[], [], []]


def test_exact_task_create__keeps_review__when_duplicate_risk_exists() -> None:
    request_intent, planning_result, _tool_route_plan, work_analysis = _exact_task_state()
    work_analysis["risks"] = [
        {
            "kind": "DUPLICATE_RISK",
            "severity": "MEDIUM",
            "description": "similar task exists",
            "evidence_refs": ["e1"],
        }
    ]
    calls: list[str] = []

    inspect_goal_and_evidence(
        request_intent=request_intent,
        planning_result=planning_result,
        evidence=[],
        work_analysis=work_analysis,
        invoke=lambda prompt_id, _input: calls.append(prompt_id)
        or {
            "schema_version": 1,
            "dimension": "review.inspect_goal_and_evidence",
            "findings": [],
        },
    )

    assert calls == ["review.inspect_goal_and_evidence"]


def _exact_task_state() -> tuple[
    dict[str, object], dict[str, object], dict[str, object], dict[str, object]
]:
    route_id = "route-task"
    request_intent: dict[str, object] = {
        "requested_resource_hints": ["TASK"],
        "requested_effect_hints": ["CREATE"],
        "ambiguity": {"requires_confirmation": False},
        "constraints": [{"kind": "RESOURCE", "field": "title", "value": "Submit report"}],
    }
    planning_result: dict[str, object] = {
        "schema_version": 2,
        "actions": [
            {
                "action_id": "action-task",
                "route_id": route_id,
                "tool_id": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {
                    "task_list_id": "@default",
                    "payload": {"title": "Submit report"},
                },
                "evidence_refs": ["e1", "message-1"],
            }
        ],
    }
    tool_route_plan: dict[str, object] = {
        "output_plan": {
            "output_mode": "ACTION",
            "output_routes": [
                {
                    "route_id": route_id,
                    "resource_type": "TASK",
                    "connector_id": "google_workspace",
                    "effect": "CREATE",
                    "selected_tool_id": "tasks_create_task",
                }
            ],
        }
    }
    work_analysis: dict[str, object] = {
        "schema_version": 2,
        "action_necessity": "REQUIRED",
        "ambiguities": [],
        "risks": [],
        "relations": [],
        "evidence_refs": ["e1"],
    }
    return request_intent, planning_result, tool_route_plan, work_analysis
