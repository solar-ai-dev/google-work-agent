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
    target = returned.get("__target__")
    if target not in _ALLOWED_TARGETS:
        raise ValueError(f"PREFLIGHT returned an unregistered target: {target!r}")
    patch = {key: value for key, value in returned.items() if state.get(key) != value}
    patch["__target__"] = target
    logical_target = returned.get("__logical_target__")
    if isinstance(logical_target, str):
        patch["__logical_target__"] = logical_target
    return patch


__all__ = ["preflight_node"]
