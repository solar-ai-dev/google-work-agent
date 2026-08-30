"""Exact input projection for deterministic dependency derivation."""

from collections.abc import Mapping, Sequence


def project_build_dependencies_input(state: Mapping[str, object]) -> dict[str, object]:
    seeds = state.get("__planning_action_seeds__")
    if not isinstance(seeds, Sequence) or isinstance(seeds, (str, bytes)):
        raise ValueError("action seeds are required")
    if not all(isinstance(item, Mapping) for item in seeds):
        raise ValueError("action seeds must be objects")
    return {"action_seeds": [dict(item) for item in seeds]}


__all__ = ["project_build_dependencies_input"]
