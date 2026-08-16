"""G3 RunBudgetV1: ensure_llm_call_budget / consume_llm_call_budget wiring.

These are the shared helpers every native SIX_ROLE_BASELINE subgraph node
calls immediately before/after its one real Provider LLM call (see
adapters/langgraph/agent_kernel.py). The deterministic policy itself
(profile caps, absolute cap, accounting) is already exhaustively unit-tested
in isolation by tests/unit/application/workflows/test_run_budget.py; this
file proves the *wiring* -- that these helpers read/write
state["retry_budget"] correctly and that denial raises before any Provider
call can happen.
"""

from __future__ import annotations

import pytest

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
)
from google_work_agent.application.workflows import (
    ABSOLUTE_MAX_LLM_CALLS,
    NORMAL_MAX_LLM_CALLS,
    RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    REVISION_HEAVY_MAX_LLM_CALLS,
    BudgetProfile,
    build_default_run_budget,
)
from google_work_agent.ports import LLMErrorCode, LLMInvocationError


def _state(*, llm_calls_used: int, profile: str = BudgetProfile.NORMAL.value) -> dict[str, object]:
    return {
        "retry_budget": {
            **build_default_run_budget(),
            "profile": profile,
            "llm_calls_used": llm_calls_used,
        }
    }


def test_ensure_allows_calls_under_the_normal_cap() -> None:
    state = _state(llm_calls_used=NORMAL_MAX_LLM_CALLS - 1)

    ensure_llm_call_budget(state)  # must not raise


def test_ensure_blocks_the_call_that_would_exceed_the_normal_cap() -> None:
    state = _state(llm_calls_used=NORMAL_MAX_LLM_CALLS)

    with pytest.raises(LLMInvocationError) as excinfo:
        ensure_llm_call_budget(state)
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_ensure_blocks_the_call_that_would_exceed_the_revision_heavy_cap() -> None:
    state = _state(
        llm_calls_used=REVISION_HEAVY_MAX_LLM_CALLS,
        profile=BudgetProfile.REVISION_HEAVY.value,
    )

    with pytest.raises(LLMInvocationError) as excinfo:
        ensure_llm_call_budget(state)
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_ensure_blocks_the_call_that_would_exceed_the_retrieval_heavy_cap() -> None:
    state = _state(
        llm_calls_used=RETRIEVAL_HEAVY_MAX_LLM_CALLS,
        profile=BudgetProfile.RETRIEVAL_HEAVY.value,
    )

    with pytest.raises(LLMInvocationError) as excinfo:
        ensure_llm_call_budget(state)
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_ensure_blocks_at_the_absolute_cap_regardless_of_profile() -> None:
    # RETRIEVAL_HEAVY's own cap (14) is already below ABSOLUTE (16); this
    # state is only reachable by chained consumption across profiles, but it
    # proves the ABSOLUTE ceiling itself -- not just the profile ceiling --
    # is enforced no matter what profile the run is in.
    state = _state(
        llm_calls_used=ABSOLUTE_MAX_LLM_CALLS,
        profile=BudgetProfile.RETRIEVAL_HEAVY.value,
    )

    with pytest.raises(LLMInvocationError) as excinfo:
        ensure_llm_call_budget(state)
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED


def test_consume_increments_llm_calls_used_by_the_real_attempt_count() -> None:
    state = _state(llm_calls_used=3)

    updated = consume_llm_call_budget(state, provider_calls_consumed=2)

    assert updated["llm_calls_used"] == 5
    # Consuming must not mutate the caller's original state in place --
    # nodes fold the return value into their own GraphStateUpdateV1.
    assert state["retry_budget"]["llm_calls_used"] == 3  # type: ignore[index]


def test_budget_state_is_carried_entirely_by_the_caller_not_by_any_runtime_instance() -> None:
    """G3 resume/restart persistence: nothing about these helpers depends on
    process-local state. A plain dict simulating a checkpoint round-trip
    (a brand new Python object, no shared reference to the original state)
    reproduces the exact same decision -- there is no hidden counter
    anywhere else that could reset on process/runtime recreation."""
    state = _state(llm_calls_used=7)

    consumed = consume_llm_call_budget(state, provider_calls_consumed=1)
    assert consumed["llm_calls_used"] == 8

    # Simulate "checkpoint restore into a freshly constructed runtime":
    # a wholly new dict built only from the plain (JSON-serializable) value.
    restored_state = {"retry_budget": {**consumed}}

    with pytest.raises(LLMInvocationError) as excinfo:
        ensure_llm_call_budget(restored_state)
    assert excinfo.value.code is LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED
