from typing import cast

import pytest

from google_work_agent.adapters.langgraph.main.nodes.finalize_node import finalize_node
from google_work_agent.adapters.langgraph.main.nodes.response_synthesis_node import (
    TerminalCommitIntentV1,
)
from google_work_agent.adapters.langgraph.main.nodes.terminal_commit_node import (
    terminal_commit_node,
)
from google_work_agent.application.use_cases.run.build_terminal_message import (
    TerminalAssistantMessageInputV1,
)


def _intent(kind: str = "COMPLETE_WRITE") -> TerminalCommitIntentV1:
    return cast(
        TerminalCommitIntentV1,
        {
            "schema_version": 1,
            "kind": kind,
            "expected_run_version": 4,
            "terminal_message": TerminalAssistantMessageInputV1(
                1, "SUCCESS", "done", ["WRITE_VERIFIED"]
            ),
            "reason_codes": ["WRITE_VERIFIED"],
        },
    )


def test_terminal_commit_dispatches__exactly_one_handler__then_verifies_truth() -> None:
    facts: dict[str, object] = {
        "status": "VERIFYING",
        "version": 4,
        "terminal_result_kind": None,
        "final_message_count": 0,
    }
    calls: list[str] = []

    def complete_write(_state: object, _intent: object) -> None:
        calls.append("complete_write")
        facts.update(
            status="COMPLETED",
            version=5,
            terminal_result_kind="SUCCESS",
            final_message_count=1,
        )

    def unexpected(_state: object, _intent: object) -> None:
        raise AssertionError("alternate terminal handler must not be called")

    patch = terminal_commit_node(
        {"run_id": "run-1", "terminal_commit_intent": _intent()},
        read_terminal_facts=lambda _run_id: facts,
        complete_answer_only=unexpected,
        complete_read_only=unexpected,
        complete_write=complete_write,
        block_run=unexpected,
        finalize_cancel=unexpected,
        resolve_recovery=unexpected,
    )

    assert calls == ["complete_write"]
    assert patch["__target__"] == "finalize"
    assert patch["terminal_commit_intent"] is None


def test_terminal_commit__replay_verifies__without_duplicate_dispatch() -> None:
    calls = 0

    def unexpected(_state: object, _intent: object) -> None:
        nonlocal calls
        calls += 1

    patch = terminal_commit_node(
        {"run_id": "run-1", "terminal_commit_intent": _intent()},
        read_terminal_facts=lambda _run_id: {
            "status": "COMPLETED",
            "version": 5,
            "terminal_result_kind": "SUCCESS",
            "final_message_count": 1,
        },
        complete_answer_only=unexpected,
        complete_read_only=unexpected,
        complete_write=unexpected,
        block_run=unexpected,
        finalize_cancel=unexpected,
        resolve_recovery=unexpected,
    )

    assert calls == 0
    assert patch["__target__"] == "finalize"


def test_terminal_commit__unknown_kind__fails_closed() -> None:
    with pytest.raises(ValueError, match="kind is invalid"):
        terminal_commit_node(
            {"run_id": "run-1", "terminal_commit_intent": _intent("UNKNOWN")},
            read_terminal_facts=lambda _run_id: {},
            complete_answer_only=lambda *_args: None,
            complete_read_only=lambda *_args: None,
            complete_write=lambda *_args: None,
            block_run=lambda *_args: None,
            finalize_cancel=lambda *_args: None,
            resolve_recovery=lambda *_args: None,
        )


def test_finalize_is_post__commit_best_effort__and_end_only() -> None:
    calls: list[str] = []

    def failed_trace(_facts: object) -> None:
        calls.append("trace")
        raise RuntimeError("observability unavailable")

    def project(_facts: object) -> None:
        calls.append("sse")

    patch = finalize_node(
        {"run_id": "run-1"},
        read_terminal_facts=lambda _run_id: {
            "status": "COMPLETED",
            "final_message_count": 1,
        },
        emit_trace=failed_trace,
        project_run_event=project,
        discard_run_transients=lambda run_id: calls.append(f"discard:{run_id}"),
    )

    assert calls == ["trace", "sse", "discard:run-1"]
    assert patch == {
        "__logical_target__": "end",
        "__target__": "end",
        "workflow_phase": "FINALIZE",
        "terminal_commit_intent": None,
        "__context_canonical_plans__": {},
        "__context_query_attempts__": [],
        "__context_read_result_handles__": [],
        "__context_read_bindings__": {},
        "__context_segment_handles__": [],
    }


def test_finalize_rejects__nonterminal__fallthrough() -> None:
    with pytest.raises(RuntimeError, match="durably terminal"):
        finalize_node(
            {"run_id": "run-1"},
            read_terminal_facts=lambda _run_id: {
                "status": "VERIFYING",
                "final_message_count": 0,
            },
            emit_trace=lambda _facts: None,
            project_run_event=lambda _facts: None,
            discard_run_transients=lambda _run_id: None,
        )
