"""Deterministic routing after ``analysis.assess_information_gaps``."""

from collections.abc import Mapping


def route_after_assess_information_gaps(state: Mapping[str, object]) -> str:
    assessment = state.get("__analysis_information_gap_assessment__")
    if not isinstance(assessment, Mapping):
        raise ValueError("information-gap assessment is required")
    return "assess_operational_risks" if assessment.get("disposition") == "COMPLETE" else "finalize"


__all__ = ["route_after_assess_information_gaps"]
