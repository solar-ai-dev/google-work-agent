from __future__ import annotations

import inspect

from google_work_agent.application.agents.planning.assemble_plan import assemble_plan
from google_work_agent.application.agents.planning.build_dependencies import build_dependencies
from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)
from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    draft_action_objective_per_output_route,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer
from google_work_agent.application.agents.planning.resolve_default_container import (
    resolve_default_container,
)
from google_work_agent.application.agents.planning.validate_plan import validate_plan


def _seed(
    action_id: str, route_id: str, *, tool_id: str, arguments: dict[str, object]
) -> dict[str, object]:
    return {
        "action_id": action_id,
        "route_id": route_id,
        "tool_id": tool_id,
        "effect": "UPDATE",
        "arguments": arguments,
        "evidence_refs": [],
    }


def test_planning_operation__inventory_is__nine_of_nine() -> None:
    assert all(
        callable(value)
        for value in (
            choose_answer_or_action_from_route,
            outline_answer,
            compose_answer,
            resolve_default_container,
            draft_action_objective_per_output_route,
            compose_arguments_per_output_route,
            build_dependencies,
            assemble_plan,
            validate_plan,
        )
    )


def test_assemble_plan__has_no__caller_dependency_authority() -> None:
    assert "dependency_candidates" in inspect.signature(assemble_plan).parameters
    seeds = [
        _seed(
            "a1", "r1", tool_id="tasks_update_task", arguments={"task_list_id": "l", "task_id": "t"}
        ),
        _seed(
            "a2", "r2", tool_id="tasks_update_task", arguments={"task_list_id": "l", "task_id": "t"}
        ),
    ]
    dependencies = build_dependencies(seeds)  # type: ignore[arg-type]
    plan = assemble_plan(
        artifact_id="p",
        revision=1,
        based_on=[],
        action_seeds=seeds,  # type: ignore[arg-type]
        dependency_candidates=dependencies,
    )
    assert plan["actions"][1]["depends_on_action_ids"] == ["a1"]


def test_build_dependencies__is_deterministic__sole_dependency_authority() -> None:
    source = inspect.getsource(assemble_plan)
    assert "build_dependencies(seeds)" not in source
    assert "compose_dependencies" not in source
    assert "generate_dependencies" not in source


def test_compose_arguments__has_no__legacy_writer_path() -> None:
    assert "writer" not in inspect.signature(compose_arguments_per_output_route).parameters
    module = __import__(
        "google_work_agent.application.agents.planning.compose_arguments_per_output_route",
        fromlist=["compose_arguments_per_output_route"],
    )
    assert "LegacyWriter" not in inspect.getsource(module)


def test_compose_arguments__has_exact__bound_schema_parameter() -> None:
    parameters = inspect.signature(compose_arguments_per_output_route).parameters
    assert "bound_tool_schemas" in parameters
    assert "user_request" not in parameters
