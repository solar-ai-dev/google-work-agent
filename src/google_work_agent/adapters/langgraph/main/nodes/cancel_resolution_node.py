"""Canonical CANCEL_RESOLUTION control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def cancel_resolution_node(
    state: Mapping[str, object],
    *,
    continue_cancel_resolution: Callable[[str], Mapping[str, object]],
) -> dict[str, object]:
    """Settle one durable cancellation step without creating a new external effect."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    returned = dict(continue_cancel_resolution(run_id))
    return {key: value for key, value in returned.items() if state.get(key) != value}


__all__ = ["cancel_resolution_node"]
