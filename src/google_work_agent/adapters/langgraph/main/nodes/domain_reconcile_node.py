"""Canonical DOMAIN_RECONCILE control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol


class DurableRunFacts(Protocol):
    status: str

    @property
    def next_allowed_commands(self) -> tuple[str, ...]: ...


_TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})


def domain_reconcile_node(
    state: Mapping[str, object],
    *,
    read_durable_run: Callable[[str], DurableRunFacts | None],
) -> dict[str, object]:
    """Route only from current durable status and its allowed commands."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    facts = read_durable_run(run_id)
    if facts is None:
        return _suspend_patch("DOMAIN_FACTS_MISSING")
    commands = frozenset(facts.next_allowed_commands)
    if facts.status == "WAITING_APPROVAL":
        return _route_patch("waiting_approval", "PREFLIGHT")
    if facts.status == "RECOVERY_REQUIRED" or "RESOLVE_RECOVERY" in commands:
        return _route_patch("recovery", "RECOVERY")
    if facts.status in _TERMINAL_STATUSES:
        return _route_patch("finalize", "FINALIZE")
    if facts.status in {"REAUTH_REQUIRED", "CANCEL_REQUESTED"}:
        return _suspend_patch(facts.status)
    return _suspend_patch("IN_FLIGHT")


def _route_patch(target: str, phase: str) -> dict[str, object]:
    return {
        "workflow_phase": phase,
        "__logical_target__": target,
        "__target__": target,
    }


def _suspend_patch(reason: str) -> dict[str, object]:
    return {
        "__logical_target__": "end",
        "__target__": "end",
        "execution_summary": {
            "result": "DOMAIN_RECONCILE_SUSPENDED",
            "reason_code": reason,
        },
    }


__all__ = ["domain_reconcile_node"]
