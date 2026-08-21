"""Build Planning dependencies from frozen route order and stable target identity."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionDependencyCandidateV1,
    PlanningActionSeedV1,
)

_TARGET_IDENTITY_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gmail_update_draft": ("GMAIL_DRAFT", ("draft_id",)),
    "gmail_send": ("GMAIL_DRAFT", ("draft_id",)),
    "tasks_update_task": ("TASK", ("task_list_id", "task_id")),
    "tasks_delete_task": ("TASK", ("task_list_id", "task_id")),
    "calendar_update_event": ("CALENDAR_EVENT", ("calendar_id", "event_id")),
    "calendar_delete_event": ("CALENDAR_EVENT", ("calendar_id", "event_id")),
}


def build_dependencies(action_seeds: Iterable[PlanningActionSeedV1]) -> tuple[ActionDependencyCandidateV1, ...]:
    """Link only consecutive actions targeting the same already-identifiable resource."""
    previous_by_target: dict[tuple[str, ...], str] = {}
    result: list[ActionDependencyCandidateV1] = []
    for seed in action_seeds:
        target = _stable_target_identity(seed)
        if target is None:
            continue
        previous = previous_by_target.get(target)
        if previous is not None:
            result.append({
                "action_id": seed["action_id"],
                "depends_on_action_id": previous,
                "reason": "SAME_RESOURCE_ORDER",
            })
        previous_by_target[target] = seed["action_id"]
    return tuple(result)


def _stable_target_identity(seed: Mapping[str, object]) -> tuple[str, ...] | None:
    tool_id = seed.get("tool_id")
    if not isinstance(tool_id, str):
        raise ValueError("tool_id is required")
    descriptor = _TARGET_IDENTITY_FIELDS.get(tool_id)
    if descriptor is None:
        return None
    kind, fields = descriptor
    arguments = seed.get("arguments")
    if not isinstance(arguments, Mapping):
        raise ValueError("arguments must be an object")
    values: list[str] = [kind]
    for field in fields:
        value = arguments.get(field)
        if not isinstance(value, str) or not value:
            return None
        values.append(value)
    return tuple(values)
