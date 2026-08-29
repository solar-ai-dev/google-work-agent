"""Deterministic edge after canonical evidence selection."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_select_evidence(state: Mapping[str, object]) -> str:
    if not isinstance(state.get("evidence_selection"), Mapping):
        raise ValueError("retrieval evidence_selection is required")
    return "assess_sufficiency"


__all__ = ["route_after_select_evidence"]
