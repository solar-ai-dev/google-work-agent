"""Canonical PREFLIGHT control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping

_ALLOWED_TARGETS = frozenset(
    {
        "action_execution",
        "waiting_approval",
        "recovery",
        "domain_reconcile",
        "response_synthesis",
        "end",
    }
)


def preflight_node(
    state: Mapping[str, object],
    *,
    check_freshness_and_claim: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Run freshness/Claim readiness without performing an external write."""

    returned = dict(check_freshness_and_claim(state))
    patch = {key: value for key, value in returned.items() if state.get(key) != value}
    target = patch.get("__target__")
    if target not in _ALLOWED_TARGETS:
        raise ValueError("PREFLIGHT returned an unregistered target")
    return patch


__all__ = ["preflight_node"]
