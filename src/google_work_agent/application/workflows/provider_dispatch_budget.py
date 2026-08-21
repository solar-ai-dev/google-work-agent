"""RunBudgetV1 accounting at the real LLM provider dispatch boundary.

The ContextVar stores only a reference to the currently authoritative
``RunBudgetV1`` object for this execution context. It is not a second counter:
``llm_calls_used`` in RunBudgetV1 remains the sole numeric/durable authority.

Native LangGraph nodes bind their current RunBudget before invoking the LLM
runtime. ``PromptInputGuardedProvider`` calls :func:`account_provider_dispatch`
immediately after prompt validation and immediately before the real provider
method. The budget is therefore consumed even when that provider call raises a
timeout/error, and primary/fallback/repair/tool-call dispatches are each seen
independently.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import cast

from google_work_agent.application.workflows.contracts import (
    BudgetDecision,
    RunBudgetV1,
    check_llm_call_budget,
    validate_run_budget_v1,
)
from google_work_agent.ports import LLMErrorCode, LLMInvocationError

_CURRENT_RUN_BUDGET: ContextVar[RunBudgetV1 | None] = ContextVar(
    "google_work_agent_current_provider_dispatch_run_budget",
    default=None,
)


def bind_provider_dispatch_budget(run_budget: RunBudgetV1) -> RunBudgetV1:
    """Bind one mutable RunBudget authority to the current execution context."""

    validated = validate_run_budget_v1(run_budget)
    run_budget.clear()
    run_budget.update(validated)
    _CURRENT_RUN_BUDGET.set(run_budget)
    return run_budget


def account_provider_dispatch() -> None:
    """Consume exactly one provider call immediately before external dispatch."""

    run_budget = _CURRENT_RUN_BUDGET.get()
    if run_budget is None:
        # Non-Run diagnostic/connection probes intentionally have no RunBudget.
        return
    decision = check_llm_call_budget(run_budget, provider_calls_requested=1)
    if decision["decision"] == BudgetDecision.DENY.value:
        raise LLMInvocationError(
            LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
            f"run LLM call budget exhausted: {decision['budget_reason_code']}",
            retryable=False,
        )
    # This is the sole increment for a real provider dispatch. Do not route it
    # through the historical post-result consumer: calls that raise must count.
    updated = dict(validate_run_budget_v1(run_budget))
    updated["llm_calls_used"] = int(updated["llm_calls_used"]) + 1
    validated = validate_run_budget_v1(updated)
    run_budget.clear()
    run_budget.update(validated)


def merge_provider_dispatch_usage(run_budget: RunBudgetV1) -> RunBudgetV1:
    """Merge actual dispatch usage into a derived RunBudget projection."""

    derived = validate_run_budget_v1(run_budget)
    authority = _CURRENT_RUN_BUDGET.get()
    if authority is None:
        return derived
    actual = validate_run_budget_v1(authority)
    merged = dict(derived)
    merged["llm_calls_used"] = actual["llm_calls_used"]
    return cast(RunBudgetV1, validate_run_budget_v1(merged))


def legacy_post_call_projection(run_budget: RunBudgetV1) -> RunBudgetV1:
    """Bridge Tool Route's pre-Wave-1C post-call ``+1`` caller.

    Tool Route still calls the historical deterministic consumer once after a
    semantic-agent call. Until that caller is retired by its own runtime-cutover
    work, return a projection whose call count is one below the already-counted
    dispatch total, so the legacy post-call increment preserves -- rather than
    duplicates -- the dispatch-authoritative total. No separate counter exists;
    this projection is derived solely from RunBudgetV1.
    """

    merged = merge_provider_dispatch_usage(run_budget)
    used = merged["llm_calls_used"]
    if used <= 0:
        return merged
    projected = dict(merged)
    projected["llm_calls_used"] = used - 1
    return cast(RunBudgetV1, validate_run_budget_v1(projected))


def current_provider_dispatch_budget() -> RunBudgetV1 | None:
    """Return the bound RunBudget authority itself, never a second counter."""

    return _CURRENT_RUN_BUDGET.get()


__all__ = [
    "account_provider_dispatch",
    "bind_provider_dispatch_budget",
    "current_provider_dispatch_budget",
    "legacy_post_call_projection",
    "merge_provider_dispatch_usage",
]
