"""Canonical post-commit FINALIZE control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping

_TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})


def finalize_node(
    state: Mapping[str, object],
    *,
    read_terminal_facts: Callable[[str], Mapping[str, object]],
    emit_trace: Callable[[Mapping[str, object]], object],
    project_run_event: Callable[[Mapping[str, object]], object],
    discard_run_transients: Callable[[str], None],
) -> dict[str, object]:
    """Verify durable truth, then publish best-effort observability and END."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    facts = read_terminal_facts(run_id)
    if facts.get("status") not in _TERMINAL_STATUSES:
        raise RuntimeError("FINALIZE requires a durably terminal Run")
    if facts.get("final_message_count") != 1:
        raise RuntimeError("FINALIZE requires exactly one final ASSISTANT Message")
    for publisher in (emit_trace, project_run_event):
        try:
            publisher(facts)
        except Exception:
            continue
    discard_run_transients(run_id)
    return {
        "__logical_target__": "end",
        "__target__": "end",
        "workflow_phase": "FINALIZE",
        "terminal_commit_intent": None,
    }


__all__ = ["finalize_node"]
