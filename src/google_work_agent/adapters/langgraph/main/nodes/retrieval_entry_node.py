"""Canonical RETRIEVAL_ENTRY control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol


class BeginRetrievalResult(Protocol):
    applied: bool
    current_status: str


def retrieval_entry_node(
    state: Mapping[str, object],
    *,
    current_run_status: Callable[[str], str],
    begin_retrieval: Callable[[str], BeginRetrievalResult],
    retrieval_node: str,
) -> dict[str, object]:
    """Validate frozen routes, enter Retrieval lifecycle, and invoke its subgraph."""

    run_id = _required_string(state.get("run_id"), "run_id")
    _require_frozen_input_routes(state)
    status = current_run_status(run_id)
    if status in {"ANALYZING", "PLANNING"}:
        transition = begin_retrieval(run_id)
        if transition.current_status != "RETRIEVING":
            return _reconcile_patch()
    elif status != "RETRIEVING":
        return _reconcile_patch()
    return {
        "workflow_phase": "CONTEXT_RETRIEVAL",
        "__logical_target__": retrieval_node,
        "__target__": retrieval_node,
    }


def _require_frozen_input_routes(state: Mapping[str, object]) -> None:
    route_plan = state.get("tool_route_plan")
    if not isinstance(route_plan, Mapping):
        raise ValueError("RETRIEVAL_ENTRY requires frozen tool_route_plan")
    input_plan = route_plan.get("input_plan")
    if not isinstance(input_plan, Mapping):
        raise ValueError("RETRIEVAL_ENTRY requires frozen input_plan")
    routes = input_plan.get("input_routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("RETRIEVAL_ENTRY requires at least one frozen input route")


def _reconcile_patch() -> dict[str, object]:
    return {
        "__logical_target__": "domain_reconcile",
        "__target__": "domain_reconcile",
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


__all__ = ["retrieval_entry_node"]
