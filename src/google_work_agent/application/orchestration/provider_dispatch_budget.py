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

The production graph invocation boundary is wrapped in
:func:`provider_dispatch_execution_scope`, which guarantees that a budget
reference bound by one start/resume/recovery invocation cannot leak into a
later unrelated invocation or diagnostic provider call. Direct callers that
need a narrower boundary can use :func:`provider_dispatch_budget_scope`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

from google_work_agent.application.orchestration.contracts import (
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
    """Bind one mutable RunBudget authority to the current execution context.

    This compatibility helper deliberately does not own lifecycle. Production
    graph execution is bounded by ``provider_dispatch_execution_scope``;
    direct callers that bind a budget themselves should prefer
    ``provider_dispatch_budget_scope`` so reset is guaranteed by ``finally``.
    """

    validated = validate_run_budget_v1(run_budget)
    run_budget.clear()
    run_budget.update(validated)
    _CURRENT_RUN_BUDGET.set(run_budget)
    return run_budget


@contextmanager
def provider_dispatch_budget_scope(run_budget: RunBudgetV1) -> Iterator[RunBudgetV1]:
    """Bind one authoritative RunBudget and always restore the prior context."""

    validated = validate_run_budget_v1(run_budget)
    run_budget.clear()
    run_budget.update(validated)
    token = _CURRENT_RUN_BUDGET.set(run_budget)
    try:
        yield run_budget
    finally:
        _CURRENT_RUN_BUDGET.reset(token)


@contextmanager
def provider_dispatch_execution_scope() -> Iterator[None]:
    """Bound the provider-budget ContextVar to one graph invocation.

    ``WorkflowInvocationCoordinator`` is the top-level start/resume/recovery
    boundary and is not recursively entered. Start from an explicitly clean
    ContextVar so a stale reference left by older/unscoped code can never be
    charged by this invocation, then use the ContextVar token lifecycle to
    guarantee cleanup on success and on any escaping exception.
    """

    if _CURRENT_RUN_BUDGET.get() is not None:
        # Compatibility cleanup for a process that entered this code with an
        # older unbounded binding already present. This is reference cleanup,
        # not numeric accounting and does not create a second authority.
        _CURRENT_RUN_BUDGET.set(None)
    token = _CURRENT_RUN_BUDGET.set(None)
    try:
        yield
    finally:
        _CURRENT_RUN_BUDGET.reset(token)


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
    "provider_dispatch_budget_scope",
    "provider_dispatch_execution_scope",
]
