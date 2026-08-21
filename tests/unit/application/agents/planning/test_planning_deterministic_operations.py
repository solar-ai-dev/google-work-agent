from __future__ import annotations

import pytest

from google_work_agent.application.agents.planning.assemble_plan import assemble_plan
from google_work_agent.application.agents.planning.build_dependencies import build_dependencies


def _seed(action_id: str, tool_id: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "action_id": action_id,
        "route_id": f"route-{action_id}",
        "tool_id": tool_id,
        "effect": "UPDATE" if "update" in tool_id else "SEND",
        "arguments": arguments,
        "evidence_refs": ["e1"],
    }


def test_dependencies_only_link_same_stable_resource() -> None:
    seeds = [
        _seed("a1", "tasks_update_task", {"task_list_id": "l1", "task_id": "t1"}),
        _seed("a2", "tasks_update_task", {"task_list_id": "l1", "task_id": "t2"}),
        _seed("a3", "tasks_update_task", {"task_list_id": "l1", "task_id": "t1"}),
    ]
    result = build_dependencies(seeds)  # type: ignore[arg-type]
    assert result == ({"action_id": "a3", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"},)


def test_assemble_plan_rejects_cycle() -> None:
    seeds = [
        _seed("a1", "tasks_update_task", {"task_list_id": "l1", "task_id": "t1"}),
        _seed("a2", "tasks_update_task", {"task_list_id": "l1", "task_id": "t2"}),
    ]
    with pytest.raises(ValueError, match="cycle"):
        assemble_plan(
            artifact_id="p1",
            revision=1,
            based_on=[],
            action_seeds=seeds,  # type: ignore[arg-type]
            dependencies=[
                {"action_id": "a1", "depends_on_action_id": "a2", "reason": "test"},
                {"action_id": "a2", "depends_on_action_id": "a1", "reason": "test"},
            ],
        )
