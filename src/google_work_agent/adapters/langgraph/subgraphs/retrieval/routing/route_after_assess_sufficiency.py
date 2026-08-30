"""Deterministic Retrieval routing after sufficiency assessment."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_assess_sufficiency(state: Mapping[str, object]) -> str:
    value = state.get("sufficiency")
    candidate = value[0] if isinstance(value, tuple) and value else value
    if isinstance(candidate, Mapping):
        disposition = candidate.get("disposition") or candidate.get("status")
        if disposition in {"NEEDS_MORE_DATA", "RETRIEVE_MORE"}:
            if not isinstance(state.get("tool_route_plan"), Mapping):
                return "finalize"
            read_result_handles = state.get("read_result_handles")
            if not isinstance(read_result_handles, list) or not read_result_handles:
                return "finalize"
            attempts = state.get("query_attempts", [])
            if not isinstance(attempts, list):
                return "finalize"
            rounds = {item.get("round_no") for item in attempts if isinstance(item, Mapping)}
            if len(rounds) < 3:
                return "plan_query"
    return "finalize"
