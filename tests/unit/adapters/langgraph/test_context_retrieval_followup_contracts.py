from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from google_work_agent.adapters.langgraph.graph_state import (
    CONTEXT_CANONICAL_PLANS_KEY,
    CONTEXT_CURRENT_ROUND_NO_KEY,
    CONTEXT_DETAIL_CANDIDATES_KEY,
    CONTEXT_FOLLOWUP_OPERATION_KEY,
    CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY,
    CONTEXT_NEXT_PAGE_HANDLES_KEY,
    CONTEXT_QUERY_ATTEMPTS_KEY,
)
from google_work_agent.adapters.langgraph.subgraphs.context_retrieval import (
    ContextRetrieverSubgraph,
)
from google_work_agent.application.ports import ConnectorReadResult
from google_work_agent.application.workflows import build_default_run_budget
from google_work_agent.application.workflows.api_acquisition import (
    RetrievalBudget,
    retrieval_query_hash,
)
from google_work_agent.application.workflows.retrieval_read_cache import (
    DetailTargetCacheEntry,
    ReadResultCacheEntry,
    RunScopedReadResultCache,
)
from google_work_agent.application.workflows.retrieval_read_executor import RetrievalReadExecutor
from google_work_agent.application.workflows.source_fetch_plan_builder import SourceFetchPlanBuilder
from google_work_agent.ports import WorkflowCorrelationContext, WorkflowStartRequest


@dataclass
class _Reader:
    calls: int = 0

    def read(self, request: object) -> ConnectorReadResult:
        del request
        self.calls += 1
        return ConnectorReadResult(snapshots=())


@dataclass
class _Acquisition:
    calls: int = 0
    materialize_error: Exception | None = None
    retrieval_budget: RetrievalBudget = field(default_factory=RetrievalBudget)

    def materialize_retrieval_read(self, **_: object) -> Any:
        if self.materialize_error is not None:
            raise self.materialize_error
        return _Materialized()

    def acquire(self, *, plans: list[object], **_: object) -> dict[str, object]:
        self.calls += 1
        self.plans = plans
        return {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": ["gmail_thread:changed"],
            "source_summaries": [_summary(["gmail_thread:changed"])],
            "missing_slots": [],
            "remaining_budget": {"sources": 1, "pages": 1, "candidates": 1, "details": 1},
        }


@dataclass
class _Planner:
    result: dict[str, object]
    calls: int = 0

    def plan(self, *, retry_budget: object, **_: object) -> tuple[dict[str, object], object]:
        self.calls += 1
        return self.result, retry_budget


@dataclass
class _Materialized:
    segment_handles: tuple[str, ...] = ("gmail_thread:next",)
    read_result_handle: str = "new-handle"
    source_summary: dict[str, object] = field(
        default_factory=lambda: _summary(["gmail_thread:next"])
    )


def _changed_plan(*, upserts: list[dict[str, object]], removals: list[str]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["MISSING"],
                "search_spec": {
                    "mode": "CHANGED",
                    "constraint_delta": {
                        "upsert_constraints": upserts,
                        "remove_constraint_kinds": removals,
                    },
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["invoice"],
        "retrieval_order": ["route-1"],
    }


@pytest.mark.parametrize(
    "kind", ["unknown", "cross_run", "wrong_route", "unsupported", "forbidden_tool"]
)
def test_detail_fetch_invalid_candidate_publishes_nothing(kind: str) -> None:
    reader = _Reader()
    cache = RunScopedReadResultCache()
    candidate = "gmail_thread:candidate"
    if kind != "unknown":
        cache.register_detail_target(
            entry=DetailTargetCacheEntry(
                run_id="other-run" if kind == "cross_run" else "run-1",
                route_id="other-route" if kind == "wrong_route" else "route-1",
                resource_handle=candidate,
                source="GMAIL",
                resource_type="UNKNOWN" if kind == "unsupported" else "GMAIL_THREAD",
                resource_id="provider-id",
                parent_resource_id=None,
                detail_tool_id="gmail_get_message"
                if kind == "forbidden_tool"
                else "gmail_get_thread",
            )
        )
    state = _state()
    state[CONTEXT_DETAIL_CANDIDATES_KEY] = {"route-1": candidate}
    result = _subgraph(cache=cache, reader=reader, acquisition=_Acquisition())._execute_detail_node(
        state
    )  # noqa: SLF001
    assert result == state
    assert reader.calls == 0
    assert result[CONTEXT_QUERY_ATTEMPTS_KEY] == []
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 0


def test_detail_fetch_valid_candidate_executes_and_publishes_once() -> None:
    reader = _Reader()
    cache = RunScopedReadResultCache()
    candidate = "gmail_thread:candidate"
    cache.register_detail_target(
        entry=DetailTargetCacheEntry(
            "run-1",
            "route-1",
            candidate,
            "GMAIL",
            "GMAIL_THREAD",
            "provider-id",
            None,
            "gmail_get_thread",
        )
    )
    state = _state()
    state[CONTEXT_DETAIL_CANDIDATES_KEY] = {"route-1": candidate}
    result = _subgraph(cache=cache, reader=reader, acquisition=_Acquisition())._execute_detail_node(
        state
    )  # noqa: SLF001
    assert reader.calls == 1
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 1
    assert len(result[CONTEXT_QUERY_ATTEMPTS_KEY]) == 1
    assert result[CONTEXT_QUERY_ATTEMPTS_KEY][0]["operation_kind"] == "DETAIL_FETCH"


def test_detail_fetch_materializer_failure_is_atomic() -> None:
    reader = _Reader()
    cache = RunScopedReadResultCache()
    candidate = "gmail_thread:candidate"
    cache.register_detail_target(
        entry=DetailTargetCacheEntry(
            "run-1",
            "route-1",
            candidate,
            "GMAIL",
            "GMAIL_THREAD",
            "provider-id",
            None,
            "gmail_get_thread",
        )
    )
    state = _state()
    state[CONTEXT_DETAIL_CANDIDATES_KEY] = {"route-1": candidate}
    result = _subgraph(
        cache=cache,
        reader=reader,
        acquisition=_Acquisition(materialize_error=RuntimeError("materialize")),
    )._execute_detail_node(state)  # noqa: SLF001
    assert reader.calls == 1
    assert result == state
    assert result[CONTEXT_QUERY_ATTEMPTS_KEY] == []
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 0


def test_next_page_invalid_cache_bindings_publish_nothing() -> None:
    for kind in ("unknown", "cross_run", "wrong_route", "wrong_query", "exhausted"):
        reader = _Reader()
        cache = RunScopedReadResultCache()
        subgraph = _subgraph(cache=cache, reader=reader, acquisition=_Acquisition())
        state = _state()
        handle = "read-1"
        if kind != "unknown":
            cache.put(
                handle=handle,
                entry=ReadResultCacheEntry(
                    run_id="other-run" if kind == "cross_run" else "run-1",
                    route_id="other-route" if kind == "wrong_route" else "route-1",
                    query_hash="other-query"
                    if kind == "wrong_query"
                    else retrieval_query_hash(cast(Any, _plan())),
                    next_page_token=None if kind == "exhausted" else "raw-token",
                    exhausted=kind == "exhausted",
                    result_handles=(),
                    result_count=0,
                ),
            )
        state[CONTEXT_NEXT_PAGE_HANDLES_KEY] = {"route-1": handle}

        assert subgraph._execute_next_page_node(state) == state  # noqa: SLF001
        assert reader.calls == 0
        assert state[CONTEXT_QUERY_ATTEMPTS_KEY] == []
        assert state[CONTEXT_CURRENT_ROUND_NO_KEY] == 0


def test_next_page_valid_handle_executes_exactly_once() -> None:
    reader = _Reader()
    cache = RunScopedReadResultCache()
    plan = _plan()
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry(
            "run-1", "route-1", retrieval_query_hash(cast(Any, plan)), "raw", False, (), 0
        ),
    )
    state = _state()
    state[CONTEXT_NEXT_PAGE_HANDLES_KEY] = {"route-1": "read-1"}

    result = _subgraph(
        cache=cache, reader=reader, acquisition=_Acquisition()
    )._execute_next_page_node(  # noqa: SLF001
        state
    )

    assert reader.calls == 1
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 1
    assert len(result[CONTEXT_QUERY_ATTEMPTS_KEY]) == 1


def test_next_page_materializer_failure_is_atomic() -> None:
    reader = _Reader()
    cache = RunScopedReadResultCache()
    plan = _plan()
    cache.put(
        handle="read-1",
        entry=ReadResultCacheEntry(
            "run-1", "route-1", retrieval_query_hash(cast(Any, plan)), "raw", False, (), 0
        ),
    )
    state = _state()
    state[CONTEXT_NEXT_PAGE_HANDLES_KEY] = {"route-1": "read-1"}

    result = _subgraph(
        cache=cache,
        reader=reader,
        acquisition=_Acquisition(materialize_error=RuntimeError("materialize")),
    )._execute_next_page_node(state)  # noqa: SLF001

    assert reader.calls == 1
    assert result == state
    assert result[CONTEXT_QUERY_ATTEMPTS_KEY] == []
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 0


@pytest.mark.parametrize(
    ("upserts", "removals", "expected_terms"),
    [
        ([{"kind": "KEYWORD", "terms": ["renewal"], "match_mode": "ANY"}], [], ["renewal"]),
        ([], ["PARTICIPANT"], ["invoice"]),
    ],
)
def test_changed_search_executes_typed_delta(
    upserts: list[dict[str, object]], removals: list[str], expected_terms: list[str]
) -> None:
    acquisition = _Acquisition()
    subgraph = _subgraph(
        cache=RunScopedReadResultCache(),
        reader=_Reader(),
        acquisition=acquisition,
        planner=_Planner(_changed_plan(upserts=upserts, removals=removals)),
    )
    state = _changed_state()

    planned = subgraph._plan_followup_node(state)  # noqa: SLF001
    assert planned[CONTEXT_FOLLOWUP_OPERATION_KEY] == "SEARCH"
    result = subgraph._execute_followup_search_node(planned)  # noqa: SLF001

    assert acquisition.calls == 1
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 1
    assert len(result[CONTEXT_QUERY_ATTEMPTS_KEY]) == 1
    plan = cast(dict[str, object], acquisition.plans[0])
    constraints = cast(dict[str, object], plan["constraints"])
    assert all(term in cast(str, constraints["query"]) for term in expected_terms)


@pytest.mark.parametrize(
    "plan",
    [
        _changed_plan(upserts=[], removals=["KEYWORD"]),
        _changed_plan(
            upserts=[{"kind": "KEYWORD", "terms": ["renewal"], "match_mode": "ANY"}],
            removals=["KEYWORD"],
        ),
        _changed_plan(
            upserts=[{"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"}],
            removals=[],
        ),
    ],
)
def test_changed_search_invalid_or_unchanged_plan_publishes_nothing(
    plan: dict[str, object],
) -> None:
    acquisition = _Acquisition()
    subgraph = _subgraph(
        cache=RunScopedReadResultCache(),
        reader=_Reader(),
        acquisition=acquisition,
        planner=_Planner(plan),
    )
    state = _changed_state()

    result = subgraph._plan_followup_node(state)  # noqa: SLF001

    assert result[CONTEXT_FOLLOWUP_OPERATION_KEY] == "FINALIZE"
    assert acquisition.calls == 0
    assert result[CONTEXT_CURRENT_ROUND_NO_KEY] == 0
    assert result[CONTEXT_QUERY_ATTEMPTS_KEY] == []


def _subgraph(
    *,
    cache: RunScopedReadResultCache,
    reader: _Reader,
    acquisition: _Acquisition,
    planner: _Planner | None = None,
) -> Any:
    subgraph = object.__new__(ContextRetrieverSubgraph)
    subgraph._read_result_cache = cache  # noqa: SLF001
    subgraph._retrieval_read_executor = RetrievalReadExecutor(  # noqa: SLF001
        connector_reader=reader,
        read_result_cache=cache,
        now_ms=lambda: 0,
        timezone_provider=lambda: "Asia/Seoul",
    )
    subgraph._acquisition_agent = acquisition  # noqa: SLF001
    subgraph._retrieval_query_planner = cast(Any, planner)  # noqa: SLF001
    subgraph._source_fetch_plan_builder = SourceFetchPlanBuilder()  # noqa: SLF001
    subgraph._id_factory = lambda: "attempt-1"  # noqa: SLF001
    subgraph._default_tasklist_id_provider = None  # noqa: SLF001
    return subgraph


def _state() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "__request__": WorkflowStartRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            request_text="test",
            selected_resource_ids=(),
            correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        ),
        "tool_route_plan": {"input_plan": {"input_routes": [_route()]}},
        "source_fetch_plans": [_plan()],
        "acquisition_result": {
            "schema_version": 1,
            "status": "COMPLETE",
            "resource_handles": [],
            "source_summaries": [],
            "missing_slots": [],
            "remaining_budget": {"sources": 1, "pages": 1, "candidates": 1, "details": 1},
        },
        CONTEXT_CURRENT_ROUND_NO_KEY: 0,
        CONTEXT_QUERY_ATTEMPTS_KEY: [],
        "retry_budget": build_default_run_budget(),
    }


def _changed_state() -> dict[str, object]:
    state = _state()
    state["request_intent"] = {
        "schema_version": 2,
        "meta": {"artifact_id": "intent", "revision": 1, "based_on": []},
        "goal": "find invoice",
        "completion_conditions": ["found"],
        "constraints": [],
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "NONE",
    }
    state[CONTEXT_FOLLOWUP_PLANNER_INPUT_KEY] = {
        "current_round_no": 0,
        "prior_query_attempts": [],
        "unresolved_sufficiency_issues": [],
        "read_result_summaries": [],
    }
    state[CONTEXT_CANONICAL_PLANS_KEY] = {"route-1": _canonical_plan()}
    return state


def _route() -> dict[str, object]:
    return {
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "GMAIL_THREAD",
        "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
        "required": True,
        "reason_codes": ["MISSING"],
    }


def _plan() -> dict[str, object]:
    return {
        "schema_version": 2,
        "source": "GMAIL",
        "priority": 1,
        "reason_codes": ["MISSING"],
        "constraints": {"query": "invoice"},
        "page_size": 1,
        "max_pages": 1,
        "max_candidates": 1,
        "detail_limit": 1,
        "required": True,
        "calendar_read_mode": None,
        "temporal_query": None,
    }


def _summary(handles: list[str]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source": "GMAIL",
        "status": "COMPLETE",
        "required": True,
        "resource_count": len(handles),
        "resource_handles": handles,
        "resources": [],
    }


def _canonical_plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "route_id": "route-1",
        "connector_id": "google_workspace",
        "resource_type": "EMAIL",
        "operation_kind": "SEARCH",
        "effective_constraints": [
            {"kind": "KEYWORD", "terms": ["invoice"], "match_mode": "ANY"},
            {
                "kind": "PARTICIPANT",
                "participants": [{"role": "SENDER", "identity": "a@example.com"}],
                "match_mode": "ANY",
            },
        ],
        "query_identity_hash": "prior",
        "prior_read_result_handle": None,
        "detail_candidate_ref": None,
    }
