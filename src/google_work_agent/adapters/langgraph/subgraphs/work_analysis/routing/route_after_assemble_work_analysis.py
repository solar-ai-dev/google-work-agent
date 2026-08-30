"""Closed router after the deterministic ``analysis.finalize`` node."""

from collections.abc import Mapping
from typing import Literal


def route_after_assemble_work_analysis(
    state: Mapping[str, object],
) -> Literal["assess_operational_risks", "end"]:
    if state.get("__work_analysis_retry_confirmation__"):
        return "assess_operational_risks"
    return "end"


__all__ = ["route_after_assemble_work_analysis"]
