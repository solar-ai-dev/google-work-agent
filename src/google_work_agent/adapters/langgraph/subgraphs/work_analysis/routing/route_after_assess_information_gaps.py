"""Deterministic Work Analysis routing after information-gap assessment."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_assess_information_gaps(state: Mapping[str, object]) -> str:
    value = state.get("information_gaps")
    if isinstance(value, Mapping) and value.get("disposition") != "COMPLETE":
        return "end"
    return "assess_operational_risks"
