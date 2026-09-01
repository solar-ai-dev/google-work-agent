"""RunBudgetV2 accounting at the real LLM provider dispatch boundary.

The ContextVar stores only a reference to the currently authoritative
``RunBudgetV2`` object for this execution context. It is not a second counter:
``llm_calls_used`` in RunBudgetV2 remains the sole numeric/durable authority.

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

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import cast

from google_work_agent.application.use_cases.run.guard_run_budget import (
    GuardRunBudgetHandler,
    GuardRunBudgetQueryV1,
    RunBudgetDeltaV1,
    RunBudgetV2,
    consume_llm_provider_calls,
    validate_run_budget_v2,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    LLMErrorCode,
    LLMInvocationError,
)

_CURRENT_RUN_BUDGET: ContextVar[RunBudgetV2 | None] = ContextVar(
    "google_work_agent_current_provider_dispatch_run_budget",
    default=None,
)
_CURRENT_RUN_ID: ContextVar[str | None] = ContextVar(
    "google_work_agent_current_provider_dispatch_run_id", default=None
)
_CURRENT_NOW_MS: ContextVar[Callable[[], int] | None] = ContextVar(
    "google_work_agent_current_provider_dispatch_clock", default=None
)


def bind_provider_dispatch_budget(run_budget: RunBudgetV2) -> RunBudgetV2:
    """Bind one mutable RunBudget authority to the current execution context."""

    validated = validate_run_budget_v2(run_budget)
    mutable = cast(dict[str, object], run_budget)
    mutable.clear()
    mutable.update(validated)
    _CURRENT_RUN_BUDGET.set(run_budget)
    if _CURRENT_RUN_ID.get() is None:
        _CURRENT_RUN_ID.set("direct-provider-dispatch")
    if _CURRENT_NOW_MS.get() is None:
        _CURRENT_NOW_MS.set(lambda: run_budget["started_at_ms"])
    return run_budget


@contextmanager
def provider_dispatch_budget_scope(run_budget: RunBudgetV2) -> Iterator[RunBudgetV2]:
    """Bind one RunBudget without replacing an enclosing execution identity."""

    validated = validate_run_budget_v2(run_budget)
    mutable = cast(dict[str, object], run_budget)
    mutable.clear()
    mutable.update(validated)
    token = _CURRENT_RUN_BUDGET.set(run_budget)
    current_run_id = _CURRENT_RUN_ID.get()
    current_clock = _CURRENT_NOW_MS.get()
    run_token = _CURRENT_RUN_ID.set(current_run_id or "direct-provider-dispatch")
    clock_token = _CURRENT_NOW_MS.set(current_clock or (lambda: run_budget["started_at_ms"]))
    try:
        yield run_budget
    finally:
        _CURRENT_NOW_MS.reset(clock_token)
        _CURRENT_RUN_ID.reset(run_token)
        _CURRENT_RUN_BUDGET.reset(token)


@contextmanager
def provider_dispatch_execution_scope(
    *, run_id: str = "direct-provider-dispatch", now_ms: Callable[[], int] = lambda: 0
) -> Iterator[None]:
    """Bound the provider-budget ContextVar to one graph invocation.

    ``WorkflowInvocationCoordinator`` is the top-level start/resume/recovery
    boundary and is not recursively entered. Start from an explicitly clean
    ContextVar so a stale reference left by older/unscoped code can never be
    charged by this invocation, then use the ContextVar token lifecycle to
    guarantee cleanup on success and on any escaping exception.
    """

    _CURRENT_RUN_BUDGET.set(None)
    _CURRENT_RUN_ID.set(run_id)
    _CURRENT_NOW_MS.set(now_ms)
    try:
        yield
    finally:
        _CURRENT_NOW_MS.set(None)
        _CURRENT_RUN_ID.set(None)
        _CURRENT_RUN_BUDGET.set(None)


def account_provider_dispatch() -> None:
    """Consume exactly one provider call immediately before external dispatch."""

    run_budget = _CURRENT_RUN_BUDGET.get()
    if run_budget is None:
        # Non-Run diagnostic/connection probes intentionally have no RunBudget.
        return
    run_id = _CURRENT_RUN_ID.get()
    now_ms = _CURRENT_NOW_MS.get()
    if run_id is None or now_ms is None:
        raise RuntimeError("provider dispatch budget is missing execution context")
    decision = GuardRunBudgetHandler()(
        GuardRunBudgetQueryV1(
            schema_version=1,
            run_id=run_id,
            current_budget=run_budget,
            requested_delta=RunBudgetDeltaV1(1, "LLM_CALL", 1),
            now_ms=now_ms(),
        )
    )
    if not decision.allowed:
        raise LLMInvocationError(
            LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
            f"run LLM call budget exhausted: {decision.reason_code}",
            retryable=False,
        )
    # This is the sole increment for a real provider dispatch. Do not route it
    # through the historical post-result consumer: calls that raise must count.
    validated = consume_llm_provider_calls(run_budget)
    mutable = cast(dict[str, object], run_budget)
    mutable.clear()
    mutable.update(validated)


def merge_provider_dispatch_usage(run_budget: RunBudgetV2) -> RunBudgetV2:
    """Merge actual dispatch usage into a derived RunBudget projection."""

    derived = validate_run_budget_v2(run_budget)
    authority = _CURRENT_RUN_BUDGET.get()
    if authority is None:
        return derived
    actual = validate_run_budget_v2(authority)
    merged = dict(derived)
    merged["llm_calls_used"] = actual["llm_calls_used"]
    return cast(RunBudgetV2, validate_run_budget_v2(merged))


def current_provider_dispatch_budget() -> RunBudgetV2 | None:
    """Return the bound RunBudget authority itself, never a second counter."""

    return _CURRENT_RUN_BUDGET.get()


def current_provider_dispatch_run_id() -> str | None:
    """Return the Run identity bound to the current workflow execution."""

    return _CURRENT_RUN_ID.get()


__all__ = [
    "account_provider_dispatch",
    "bind_provider_dispatch_budget",
    "current_provider_dispatch_budget",
    "current_provider_dispatch_run_id",
    "merge_provider_dispatch_usage",
    "provider_dispatch_budget_scope",
    "provider_dispatch_execution_scope",
]
