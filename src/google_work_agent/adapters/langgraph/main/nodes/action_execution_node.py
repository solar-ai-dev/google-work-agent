"""Canonical ACTION_EXECUTION control node."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState


def action_execution_node(
    state: GraphState,
    *,
    execute_claimed_action: Callable[[GraphState], GraphState],
) -> GraphState:
    """Execute one already-claimed action without creating a resume authority."""

    returned = dict(execute_claimed_action(state))
    return cast(
        GraphState,
        {key: value for key, value in returned.items() if state.get(key) != value},
    )


__all__ = ["action_execution_node"]
