from __future__ import annotations

import pytest

from google_work_agent.application.workflows.planning_plan_assembler import (
    PlanningAssemblyError,
    assemble_action_plan_draft_v2,
    derive_action_dependencies_deterministically,
    materialize_action_seeds,
)


def _routes() -> tuple[dict[str, object], ...]:
    return (
        {
            "route_id": "route-task",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "tasks_create_task",
            "reason_codes": ["USER_REQUEST"],
        },
        {
            "route_id": "route-mail",
            "resource_type": "GMAIL_DRAFT",
            "connector_id": "google_workspace",
            "effect": "CREATE",
            "selected_tool_id": "gmail_create_draft",
            "reason_codes": ["USER_REQUEST"],
        },
    )


def _candidates() -> tuple[dict[str, object], ...]:
    return (
        {
            "schema_version": 1,
            "route_id": "route-task",
            "arguments": {"task_list_id": "list-1", "payload": {"title": "Task"}},
            "evidence_refs": ["ev-task"],
        },
        {
            "schema_version": 1,
            "route_id": "route-mail",
            "arguments": {
                "payload": {
                    "to": ["a@example.com"],
                    "subject": "Subject",
                    "body": "Body",
                }
            },
            "evidence_refs": ["ev-mail"],
        },
    )


def test_materialize_seeds_copies_tool_and_effect_from_frozen_routes() -> None:
    ids = iter(("action-1", "action-2"))
    seeds = materialize_action_seeds(
        output_routes=_routes(),  # type: ignore[arg-type]
        argument_candidates=_candidates(),  # type: ignore[arg-type]
        action_id_factory=lambda: next(ids),
    )

    assert seeds[0]["tool_id"] == "tasks_create_task"
    assert seeds[0]["effect"] == "CREATE"
    assert seeds[1]["tool_id"] == "gmail_create_draft"
    assert seeds[1]["effect"] == "CREATE"
    assert "tool_id" not in _candidates()[0]
    assert "effect" not in _candidates()[0]


def test_argument_candidates_must_be_set_equal_to_output_routes() -> None:
    with pytest.raises(PlanningAssemblyError, match="must match frozen output routes"):
        materialize_action_seeds(
            output_routes=_routes(),  # type: ignore[arg-type]
            argument_candidates=_candidates()[:1],  # type: ignore[arg-type]
            action_id_factory=lambda: "action",
        )


def test_derive_dependencies_orders_same_existing_resource_only() -> None:
    seeds = (
        {
            "action_id": "action-update",
            "route_id": "route-update",
            "tool_id": "gmail_update_draft",
            "effect": "UPDATE",
            "arguments": {"draft_id": "draft-1", "payload": {"body": "updated"}},
            "evidence_refs": ["ev-1"],
        },
        {
            "action_id": "action-task",
            "route_id": "route-task",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {
                "task_list_id": "list-1",
                "task_id": "task-1",
                "payload": {"status": "completed"},
            },
            "evidence_refs": ["ev-2"],
        },
        {
            "action_id": "action-send",
            "route_id": "route-send",
            "tool_id": "gmail_send",
            "effect": "SEND",
            "arguments": {"draft_id": "draft-1"},
            "evidence_refs": ["ev-3"],
        },
        {
            "action_id": "action-delete-task",
            "route_id": "route-delete-task",
            "tool_id": "tasks_delete_task",
            "effect": "DELETE",
            "arguments": {"task_list_id": "list-1", "task_id": "task-1"},
            "evidence_refs": ["ev-4"],
        },
    )

    dependencies = derive_action_dependencies_deterministically(seeds)  # type: ignore[arg-type]

    assert dependencies == (
        {
            "action_id": "action-send",
            "depends_on_action_id": "action-update",
            "reason": "SAME_RESOURCE_ORDER",
        },
        {
            "action_id": "action-delete-task",
            "depends_on_action_id": "action-task",
            "reason": "SAME_RESOURCE_ORDER",
        },
    )


def test_derive_dependencies_does_not_invent_create_resource_identity() -> None:
    ids = iter(("action-1", "action-2"))
    seeds = materialize_action_seeds(
        output_routes=_routes(),  # type: ignore[arg-type]
        argument_candidates=_candidates(),  # type: ignore[arg-type]
        action_id_factory=lambda: next(ids),
    )

    assert derive_action_dependencies_deterministically(seeds) == ()


def test_assemble_plan_derives_dependencies_when_not_supplied() -> None:
    seeds = (
        {
            "action_id": "action-update",
            "route_id": "route-update",
            "tool_id": "calendar_update_event",
            "effect": "UPDATE",
            "arguments": {
                "calendar_id": "cal-1",
                "event_id": "event-1",
                "payload": {"title": "new"},
            },
            "evidence_refs": ["ev-1"],
        },
        {
            "action_id": "action-delete",
            "route_id": "route-delete",
            "tool_id": "calendar_delete_event",
            "effect": "DELETE",
            "arguments": {"calendar_id": "cal-1", "event_id": "event-1"},
            "evidence_refs": ["ev-2"],
        },
    )

    plan = assemble_action_plan_draft_v2(
        artifact_id="plan-artifact-1",
        revision=1,
        based_on=[],
        action_seeds=seeds,  # type: ignore[arg-type]
    )

    assert plan["actions"][0]["depends_on_action_ids"] == []
    assert plan["actions"][1]["depends_on_action_ids"] == ["action-update"]


def test_assemble_plan_applies_valid_dependency_candidates() -> None:
    ids = iter(("action-1", "action-2"))
    seeds = materialize_action_seeds(
        output_routes=_routes(),  # type: ignore[arg-type]
        argument_candidates=_candidates(),  # type: ignore[arg-type]
        action_id_factory=lambda: next(ids),
    )

    plan = assemble_action_plan_draft_v2(
        artifact_id="plan-artifact-1",
        revision=1,
        based_on=[{"artifact_id": "route-plan-1", "revision": 2}],
        action_seeds=seeds,
        dependency_candidates=[
            {
                "action_id": "action-2",
                "depends_on_action_id": "action-1",
                "reason": "draft after task",
            }
        ],
    )

    assert plan == {
        "schema_version": 2,
        "meta": {
            "artifact_id": "plan-artifact-1",
            "revision": 1,
            "based_on": [{"artifact_id": "route-plan-1", "revision": 2}],
        },
        "actions": [
            {
                "action_id": "action-1",
                "route_id": "route-task",
                "tool_id": "tasks_create_task",
                "effect": "CREATE",
                "arguments": {"task_list_id": "list-1", "payload": {"title": "Task"}},
                "evidence_refs": ["ev-task"],
                "depends_on_action_ids": [],
            },
            {
                "action_id": "action-2",
                "route_id": "route-mail",
                "tool_id": "gmail_create_draft",
                "effect": "CREATE",
                "arguments": {
                    "payload": {
                        "to": ["a@example.com"],
                        "subject": "Subject",
                        "body": "Body",
                    }
                },
                "evidence_refs": ["ev-mail"],
                "depends_on_action_ids": ["action-1"],
            },
        ],
    }


def test_assemble_plan_rejects_dependency_cycle() -> None:
    ids = iter(("action-1", "action-2"))
    seeds = materialize_action_seeds(
        output_routes=_routes(),  # type: ignore[arg-type]
        argument_candidates=_candidates(),  # type: ignore[arg-type]
        action_id_factory=lambda: next(ids),
    )

    with pytest.raises(PlanningAssemblyError, match="cycle"):
        assemble_action_plan_draft_v2(
            artifact_id="plan-artifact-1",
            revision=1,
            based_on=[],
            action_seeds=seeds,
            dependency_candidates=[
                {
                    "action_id": "action-1",
                    "depends_on_action_id": "action-2",
                    "reason": "a",
                },
                {
                    "action_id": "action-2",
                    "depends_on_action_id": "action-1",
                    "reason": "b",
                },
            ],
        )


def test_assemble_plan_rejects_dependency_outside_plan() -> None:
    ids = iter(("action-1", "action-2"))
    seeds = materialize_action_seeds(
        output_routes=_routes(),  # type: ignore[arg-type]
        argument_candidates=_candidates(),  # type: ignore[arg-type]
        action_id_factory=lambda: next(ids),
    )

    with pytest.raises(PlanningAssemblyError, match="outside this plan"):
        assemble_action_plan_draft_v2(
            artifact_id="plan-artifact-1",
            revision=1,
            based_on=[],
            action_seeds=seeds,
            dependency_candidates=[
                {
                    "action_id": "action-2",
                    "depends_on_action_id": "outside-action",
                    "reason": "invalid",
                }
            ],
        )
