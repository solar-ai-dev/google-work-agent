"""Deterministic Retrieval routing after sufficiency assessment."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_assess_sufficiency(state: Mapping[str, object]) -> str:
    value = state.get("sufficiency")
    candidate = value[0] if isinstance(value, tuple) and value else value
    if isinstance(candidate, Mapping):
        disposition = candidate.get("disposition") or candidate.get("status")
        if disposition in {"NEEDS_MORE_DATA", "RETRIEVE_MORE"}:
            return "plan_query"
    return "finalize_retrieval"
