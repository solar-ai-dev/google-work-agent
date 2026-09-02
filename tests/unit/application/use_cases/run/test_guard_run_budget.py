import pytest

from google_work_agent.application.use_cases.run.guard_run_budget import (
    GuardRunBudgetHandler,
    GuardRunBudgetQueryV1,
    RunBudgetDeltaV1,
    RunBudgetV2,
)


def _budget(**overrides: object) -> RunBudgetV2:
    value: RunBudgetV2 = {
        "schema_version": 2,
        "profile": "NORMAL",
        "started_at_ms": 100,
        "max_execution_ms": 1_000,
        "llm_calls_used": 2,
        "llm_call_limit": 14,
        "connector_calls_used": 3,
        "max_connector_calls": 5,
        "source_page_calls_used": 0,
        "max_source_page_calls": 8,
        "detail_fetches_used": 0,
        "max_detail_fetches": 12,
        "context_tokens_used": 0,
        "max_context_tokens": 1_000,
        "retry_attempts_used": 0,
        "max_retry_attempts": 2,
        "absolute_llm_call_limit": 24,
        "schema_repairs_used_by_node": {},
        "semantic_revisions_used_by_failure": {},
        "planning_revisions_used": 0,
        "review_rechecks_used": 0,
        "additional_retrieval_rounds_used": 0,
    }
    value.update(overrides)  # type: ignore[typeddict-item]
    return value


def test_guard_run__budget_allows_without__mutating_current_budget() -> None:
    budget = _budget()
    before = budget.copy()

    result = GuardRunBudgetHandler()(
        GuardRunBudgetQueryV1(1, "run-1", budget, RunBudgetDeltaV1(1, "CONNECTOR_CALL", 1), 150)
    )

    assert result.allowed is True
    assert result.reason_code == "OK"
    assert result.remaining_units == 1
    assert result.elapsed_ms == 50
    assert budget == before


@pytest.mark.parametrize(
    ("delta", "overrides", "reason"),
    [
        (RunBudgetDeltaV1(1, "LLM_CALL", 1), {"llm_calls_used": 14}, "LLM_LIMIT"),
        (
            RunBudgetDeltaV1(1, "DETAIL_FETCH", 2),
            {"detail_fetches_used": 11},
            "DETAIL_FETCH_LIMIT",
        ),
    ],
)
def test_guard_run__budget_fails_before__exceeding_hard_limit(
    delta: RunBudgetDeltaV1, overrides: dict[str, object], reason: str
) -> None:
    result = GuardRunBudgetHandler()(
        GuardRunBudgetQueryV1(1, "run-1", _budget(**overrides), delta, 150)
    )
    assert result.allowed is False
    assert result.reason_code == reason


def test_guard_run__budget_blocks__at_execution_deadline() -> None:
    result = GuardRunBudgetHandler()(
        GuardRunBudgetQueryV1(
            1,
            "run-1",
            _budget(),
            RunBudgetDeltaV1(1, "LLM_CALL", 1),
            1_100,
        )
    )
    assert result.allowed is False
    assert result.reason_code == "MAX_EXECUTION_TIME"
