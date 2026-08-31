from __future__ import annotations

import pytest

from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    RequiredContainerUnresolvedError,
    resolve_default_container,
)


def _route() -> dict[str, object]:
    return {
        "route_id": "r1",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "tasks_create_task",
        "reason_codes": [],
    }


def test_explicit_container_wins_and_is_const_bound() -> None:
    result = resolve_default_container(
        route=_route(),  # type: ignore[arg-type]
        selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        explicit_container_id="explicit",
        default_tasklist_id_provider=lambda: "default",
    )
    assert result["immutable_arguments"] == {"task_list_id": "explicit"}
    assert result["argument_schema"]["properties"]["task_list_id"]["const"] == "explicit"  # type: ignore[index]


def test_required_container_without_source_fails_before_prompt() -> None:
    with pytest.raises(RequiredContainerUnresolvedError):
        resolve_default_container(
            route=_route(),  # type: ignore[arg-type]
            selected_tool_schema=planning_tool_argument_schema("tasks_create_task"),
        )
