"""Deterministic routing after ``analysis.assess_operational_risks``."""

from collections.abc import Mapping


def route_after_assess_operational_risks(_state: Mapping[str, object]) -> str:
    return "finalize"


__all__ = ["route_after_assess_operational_risks"]
