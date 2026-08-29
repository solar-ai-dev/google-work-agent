"""Deterministic terminal edge after canonical Retrieval finalization."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_finalize_retrieval(state: Mapping[str, object]) -> str:
    if not isinstance(state.get("final_result"), Mapping):
        raise ValueError("retrieval final_result is required")
    return "end"


__all__ = ["route_after_finalize_retrieval"]
