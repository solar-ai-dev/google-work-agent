"""Canonical VERIFICATION control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def verification_node(
    state: Mapping[str, object],
    *,
    verify_durable_effects: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Re-read and store verification through the canonical Application boundary."""

    returned = dict(verify_durable_effects(state))
    return {key: value for key, value in returned.items() if state.get(key) != value}


__all__ = ["verification_node"]
