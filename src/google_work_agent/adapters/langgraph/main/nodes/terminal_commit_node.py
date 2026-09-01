"""Canonical closed TERMINAL_COMMIT dispatcher."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
    validate_terminal_commit_intent,
)

type TerminalHandler = Callable[[Mapping[str, object], TerminalCommitIntentV1], object]

_TERMINAL_STATUSES = frozenset({"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"})


def terminal_commit_node(
    state: Mapping[str, object],
    *,
    read_terminal_facts: Callable[[str], Mapping[str, object]],
    complete_answer_only: TerminalHandler,
    complete_write: TerminalHandler,
    block_run: TerminalHandler,
    finalize_cancel: TerminalHandler,
    resolve_recovery: TerminalHandler,
) -> dict[str, object]:
    """Invoke exactly one existing lifecycle handler, or verify its durable replay."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    intent = validate_terminal_commit_intent(state.get("terminal_commit_intent"))
    before = read_terminal_facts(run_id)
    if _is_committed(before):
        _verify_committed(before, intent)
    else:
        handler = {
            "COMPLETE_ANSWER_ONLY": complete_answer_only,
            "COMPLETE_WRITE": complete_write,
            "BLOCK_RUN": block_run,
            "FINALIZE_CANCEL": finalize_cancel,
            "RECOVERY_ACCEPT_PARTIAL": resolve_recovery,
            "RECOVERY_CANCEL": resolve_recovery,
            "RECOVERY_FAIL": resolve_recovery,
        }.get(intent["kind"])
        if handler is None:
            raise ValueError("terminal commit kind has no registered handler")
        handler(state, intent)
        _verify_committed(read_terminal_facts(run_id), intent)
    return {
        "__logical_target__": "finalize",
        "__target__": "finalize",
        "workflow_phase": "TERMINAL_COMMIT",
        "terminal_commit_intent": None,
    }


def _is_committed(facts: Mapping[str, object]) -> bool:
    return facts.get("status") in _TERMINAL_STATUSES


def _verify_committed(facts: Mapping[str, object], intent: TerminalCommitIntentV1) -> None:
    status = facts.get("status")
    result_kind = facts.get("terminal_result_kind")
    final_message_count = facts.get("final_message_count")
    version = facts.get("version")
    if status not in _TERMINAL_STATUSES:
        raise RuntimeError("terminal lifecycle handler did not commit a terminal Run")
    if result_kind not in {"SUCCESS", "PARTIAL", "BLOCKED", "FAILED", "CANCELLED"}:
        raise RuntimeError("terminal Run is missing terminal_result_kind")
    if final_message_count != 1:
        raise RuntimeError("terminal Run must have exactly one final ASSISTANT Message")
    if not isinstance(version, int) or version < intent["expected_run_version"]:
        raise RuntimeError("terminal Run version is older than terminal intent")


__all__ = ["terminal_commit_node"]
