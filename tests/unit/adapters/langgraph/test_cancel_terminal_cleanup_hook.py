from google_work_agent.adapters.langgraph.freshness_workflow import (
    LangGraphWorkflowRuntime,
)


class _RunScopedStore:
    def __init__(self) -> None:
        self.discarded: list[str] = []

    def discard_run(self, *, run_id: str) -> None:
        self.discarded.append(run_id)


class _LlmRuntime:
    def __init__(self) -> None:
        self.discarded: list[str] = []

    def discard_run(self, *, run_id: str) -> None:
        self.discarded.append(run_id)


def test_cancel_terminal_cleanup_hook_discards_read_evidence_and_llm_run_state() -> None:
    runtime = object.__new__(LangGraphWorkflowRuntime)
    evidence = _RunScopedStore()
    read_cache = _RunScopedStore()
    llm = _LlmRuntime()
    runtime._evidence_store = evidence
    runtime._read_result_cache = read_cache
    runtime._llm_runtime = llm

    runtime.discard_run_transients("run-1")

    assert evidence.discarded == ["run-1"]
    assert read_cache.discarded == ["run-1"]
    assert llm.discarded == ["run-1"]
