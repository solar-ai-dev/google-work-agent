"""Canonical RECOVERY control node."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState


def recovery_node(
    state: GraphState,
    *,
    recover_from_durable_facts: Callable[[GraphState], GraphState],
) -> GraphState:
    """Run one durable recovery step; never infer or replay a Write from Graph state."""

    returned = dict(recover_from_durable_facts(state))
    return cast(
        GraphState,
        {key: value for key, value in returned.items() if state.get(key) != value},
    )


__all__ = ["recovery_node"]
