"""Canonical RECOVERY control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def recovery_node(
    state: Mapping[str, object],
    *,
    recover_from_durable_facts: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Run one durable recovery step; never infer or replay a Write from Graph state."""

    returned = dict(recover_from_durable_facts(state))
    return {key: value for key, value in returned.items() if state.get(key) != value}


__all__ = ["recovery_node"]
