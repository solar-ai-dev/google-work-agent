"""Closed router after the deterministic ``analysis.finalize`` node."""

from collections.abc import Mapping


def route_after_assemble_work_analysis(state: Mapping[str, object]) -> str:
    if state.get("final_analysis") is None:
        raise ValueError("analysis.finalize must produce final_analysis")
    return "end"


__all__ = ["route_after_assemble_work_analysis"]
