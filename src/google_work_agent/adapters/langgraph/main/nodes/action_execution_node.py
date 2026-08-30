"""Canonical ACTION_EXECUTION control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def action_execution_node(
    state: Mapping[str, object],
    *,
    execute_claimed_action: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Execute one already-claimed action without creating a resume authority."""

    returned = dict(execute_claimed_action(state))
    return {key: value for key, value in returned.items() if state.get(key) != value}


__all__ = ["action_execution_node"]
