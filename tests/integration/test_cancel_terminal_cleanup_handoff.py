"""Cancellation terminal cleanup handoff contract."""

from __future__ import annotations

import inspect

from google_work_agent.adapters.langgraph.freshness_workflow import (
    LangGraphWorkflowRuntime,
)
from google_work_agent.application.coordinator import LocalRunCoordinator


def test_cancel_terminal_caller_invokes_run_scoped_transient_cleanup() -> None:
    source = inspect.getsource(LocalRunCoordinator._continue_cancellation)

    assert "response.applied" in source
    assert "RunStatus.CANCELLED.value" in source
    assert "discard_run_transients" in source


def test_runtime_transient_hook_cleans_exact_run_scoped_owners() -> None:
    source = inspect.getsource(LangGraphWorkflowRuntime.discard_run_transients)

    assert "_evidence_store.discard_run" in source
    assert "_read_result_cache.discard_run" in source
    assert "_llm_runtime.discard_run" in source
