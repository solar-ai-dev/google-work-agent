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
    consume_llm_provider_calls,
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
    # Keep the caller-owned object as the authority. Validation above is
    # fail-closed, while mutation below preserves object identity so a failed
    # provider dispatch is visible to the owning graph state even though no
    # StructuredLLMResult is produced.
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
    updated = consume_llm_provider_calls(run_budget, provider_calls_consumed=1)
    run_budget.clear()
    run_budget.update(updated)


def merge_provider_dispatch_usage(run_budget: RunBudgetV1) -> RunBudgetV1:
    """Merge actual dispatch usage into a derived RunBudget projection.

    Semantic-revision guards return a copied RunBudget carrying their signature
    update. The provider boundary may meanwhile have incremented the bound
    authority. Preserve all fields from the derived projection, replacing only
    ``llm_calls_used`` with the actual dispatch authority value.
    """

    derived = validate_run_budget_v1(run_budget)
    authority = _CURRENT_RUN_BUDGET.get()
    if authority is None:
        return derived
    actual = validate_run_budget_v1(authority)
    merged = dict(derived)
    merged["llm_calls_used"] = actual["llm_calls_used"]
    return cast(RunBudgetV1, validate_run_budget_v1(merged))


def current_provider_dispatch_budget() -> RunBudgetV1 | None:
    """Test/adapter inspection helper; returns the RunBudget authority itself."""

    return _CURRENT_RUN_BUDGET.get()


__all__ = [
    "account_provider_dispatch",
    "bind_provider_dispatch_budget",
    "current_provider_dispatch_budget",
    "merge_provider_dispatch_usage",
]
