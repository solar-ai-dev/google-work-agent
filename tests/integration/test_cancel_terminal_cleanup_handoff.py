"""Cancellation terminal cleanup handoff contract."""

from __future__ import annotations

import inspect

from google_work_agent.adapters.langgraph.main.workflow import (
    LangGraphWorkflowRuntime,
)


def test_runtime_transient__hook_cleans_exact__run_scoped_owners() -> None:
    source = inspect.getsource(LangGraphWorkflowRuntime.discard_run_transients)

    assert "_evidence_store.discard_run" in source
    assert "_read_result_cache.discard_run" in source
    assert "_llm_runtime.discard_run" in source
