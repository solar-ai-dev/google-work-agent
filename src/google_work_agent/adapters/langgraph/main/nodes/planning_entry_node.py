"""Canonical PLANNING_ENTRY control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol


class BeginPlanningResult(Protocol):
    applied: bool
    current_status: str


def planning_entry_node(
    state: Mapping[str, object],
    *,
    current_run_status: Callable[[str], str],
    begin_planning: Callable[[str], BeginPlanningResult],
    planning_node: str,
    planning_logical_node: str | None = None,
) -> dict[str, object]:
    """Enter the existing deterministic Planning boundary without a pseudo-node."""

    run_id = _required_string(state.get("run_id"), "run_id")
    status = current_run_status(run_id)
    if status in {"ANALYZING", "RETRIEVING"}:
        transition = begin_planning(run_id)
        if transition.current_status != "PLANNING":
            return _reconcile_patch()
    elif status != "PLANNING":
        return _reconcile_patch()
    return {
        "workflow_phase": "SOLUTION_PLANNING",
        "__logical_target__": planning_logical_node or planning_node,
        "__target__": planning_node,
    }


def _reconcile_patch() -> dict[str, object]:
    return {
        "__logical_target__": "domain_reconcile",
        "__target__": "domain_reconcile",
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


__all__ = ["planning_entry_node"]
