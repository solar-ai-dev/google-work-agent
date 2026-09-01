"""Canonical INITIALIZE control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisResult


def initialize_node(
    state: Mapping[str, object],
    *,
    start_analysis: Callable[[str], StartAnalysisResult],
    request_node: str,
    request_logical_node: str | None = None,
) -> dict[str, object]:
    """Apply ``run.start_analysis`` and project only Main control fields."""

    run_id = _required_string(state.get("run_id"), "run_id")
    result = start_analysis(run_id)
    if result.current_status == "ANALYZING":
        return {
            "workflow_phase": "REQUEST_ANALYSIS",
            "__logical_target__": request_logical_node or request_node,
            "__target__": request_node,
        }
    return {
        "workflow_phase": "INITIALIZE",
        "__logical_target__": "domain_reconcile",
        "__target__": "domain_reconcile",
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


__all__ = ["initialize_node"]
