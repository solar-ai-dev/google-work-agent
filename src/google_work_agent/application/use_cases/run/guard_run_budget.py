"""Decide whether one outbound operation fits the current Run budget."""

from dataclasses import dataclass
from typing import Literal, TypedDict

RunBudgetOperationKindV1 = Literal[
    "LLM_CALL",
    "CONNECTOR_CALL",
    "SOURCE_PAGE",
    "DETAIL_FETCH",
    "RETRY_ATTEMPT",
    "CONTEXT_MATERIALIZATION",
]


class RunBudgetV2(TypedDict):
    schema_version: Literal[2]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    started_at_ms: int
    max_execution_ms: int
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    absolute_llm_call_limit: Literal[24]
    schema_repairs_used_by_node: dict[str, int]
    semantic_revisions_used_by_failure: dict[str, int]
    planning_revisions_used: int
    review_rechecks_used: int
    additional_retrieval_rounds_used: int


@dataclass(frozen=True, slots=True)
class RunBudgetDeltaV1:
    schema_version: Literal[1]
    operation_kind: RunBudgetOperationKindV1
    units: int


@dataclass(frozen=True, slots=True)
class GuardRunBudgetQueryV1:
    schema_version: Literal[1]
    run_id: str
    current_budget: RunBudgetV2
    requested_delta: RunBudgetDeltaV1
    now_ms: int


@dataclass(frozen=True, slots=True)
class GuardRunBudgetResultV1:
    schema_version: Literal[1]
    allowed: bool
    reason_code: Literal[
        "OK",
        "MAX_EXECUTION_TIME",
        "LLM_LIMIT",
        "CONNECTOR_LIMIT",
        "SOURCE_PAGE_LIMIT",
        "DETAIL_FETCH_LIMIT",
        "RETRY_LIMIT",
        "CONTEXT_LIMIT",
    ]
    remaining_units: int
    elapsed_ms: int


_DIMENSIONS: dict[RunBudgetOperationKindV1, tuple[str, str, str]] = {
    "LLM_CALL": ("llm_calls_used", "llm_call_limit", "LLM_LIMIT"),
    "CONNECTOR_CALL": (
        "connector_calls_used",
        "max_connector_calls",
        "CONNECTOR_LIMIT",
    ),
    "SOURCE_PAGE": (
        "source_page_calls_used",
        "max_source_page_calls",
        "SOURCE_PAGE_LIMIT",
    ),
    "DETAIL_FETCH": ("detail_fetches_used", "max_detail_fetches", "DETAIL_FETCH_LIMIT"),
    "RETRY_ATTEMPT": ("retry_attempts_used", "max_retry_attempts", "RETRY_LIMIT"),
    "CONTEXT_MATERIALIZATION": (
        "context_tokens_used",
        "max_context_tokens",
        "CONTEXT_LIMIT",
    ),
}


class GuardRunBudgetHandler:
    def __call__(self, query: GuardRunBudgetQueryV1) -> GuardRunBudgetResultV1:
        if (
            query.schema_version != 1
            or not query.run_id.strip()
            or query.requested_delta.schema_version != 1
            or query.requested_delta.units < 1
            or query.now_ms < 0
            or query.current_budget.get("schema_version") != 2
        ):
            raise ValueError("invalid run-budget query")
        budget = query.current_budget
        elapsed_ms = max(0, query.now_ms - budget["started_at_ms"])
        if elapsed_ms >= budget["max_execution_ms"]:
            return GuardRunBudgetResultV1(1, False, "MAX_EXECUTION_TIME", 0, elapsed_ms)

        used_name, limit_name, reason = _DIMENSIONS[query.requested_delta.operation_kind]
        used = int(budget[used_name])  # type: ignore[literal-required]
        limit = int(budget[limit_name])  # type: ignore[literal-required]
        if query.requested_delta.operation_kind == "LLM_CALL":
            limit = min(limit, int(budget["absolute_llm_call_limit"]))
        remaining = max(0, limit - used)
        if query.requested_delta.units > remaining:
            return GuardRunBudgetResultV1(
                1,
                False,
                reason,  # type: ignore[arg-type]
                remaining,
                elapsed_ms,
            )
        return GuardRunBudgetResultV1(
            1,
            True,
            "OK",
            remaining - query.requested_delta.units,
            elapsed_ms,
        )


__all__ = [
    "GuardRunBudgetHandler",
    "GuardRunBudgetQueryV1",
    "GuardRunBudgetResultV1",
    "RunBudgetDeltaV1",
    "RunBudgetOperationKindV1",
    "RunBudgetV2",
]
