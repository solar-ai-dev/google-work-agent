from google_work_agent.application.agents.planning.build_dependencies import build_dependencies


def test_only_same_stable_resource_is_ordered() -> None:
    seeds = [
        {
            "action_id": "a1",
            "route_id": "r1",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {"task_list_id": "l", "task_id": "t"},
            "evidence_refs": ["e1"],
        },
        {
            "action_id": "a2",
            "route_id": "r2",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {"task_list_id": "l", "task_id": "t"},
            "evidence_refs": ["e1"],
        },
    ]
    assert build_dependencies(seeds) == (  # type: ignore[arg-type]
        {"action_id": "a2", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"},
    )
