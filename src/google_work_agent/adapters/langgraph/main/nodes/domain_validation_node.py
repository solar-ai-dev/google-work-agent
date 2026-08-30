"""Canonical DOMAIN_VALIDATION control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping

_ALLOWED_TARGETS = frozenset(
    {
        "waiting_approval",
        "preflight",
        "response_synthesis",
        "finalize",
        "domain_reconcile",
        "end",
    }
)


def domain_validation_node(
    state: Mapping[str, object],
    *,
    validate_and_project: Callable[[Mapping[str, object]], Mapping[str, object]],
) -> dict[str, object]:
    """Invoke the existing schema/policy/Domain guard chain and return its patch."""

    patch = dict(validate_and_project(state))
    target = patch.get("__target__")
    if target not in _ALLOWED_TARGETS:
        raise ValueError("DOMAIN_VALIDATION returned an unregistered target")
    return patch


__all__ = ["domain_validation_node"]
