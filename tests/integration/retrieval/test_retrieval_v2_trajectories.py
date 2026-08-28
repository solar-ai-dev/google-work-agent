"""Compiled Context Retriever V2 integration trajectories."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourcePage,
    ResourceType,
)
from tests.integration.langgraph.test_runtime import (
    FIXTURE_ROOT,
    FakeGoogleGateway,
    ProductFixtureSnapshotLoader,
    _clear_intent,
    _llm_result,
    _make_runtime_with_llm,
    _runtime_active_manifest_path,
    _seed_runtime_database,
    _start_request,
    _synthesize_tool_route_candidate,
)
from tests.support.fakes.google_gateway import GoogleGatewayCallRecord


class _InitialSearchLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def invoke_structured(self, **kwargs: object) -> object:
        self.calls.append(dict(kwargs))
        prompt_ref = kwargs["prompt_ref"]
        prompt_id = prompt_ref.prompt_id
        prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
        if prompt_id == "tool_routing.determine_io_resources":
            return _llm_result(
                _synthesize_tool_route_candidate(cast(Any, prompt_input["request_intent"]))
            )
        if prompt_id == "retrieval.plan_query":
            route_id = cast(list[dict[str, object]], prompt_input["input_routes"])[0]["route_id"]
            return _llm_result(
                {
                    "schema_version": 2,
                    "route_queries": [
                        {
                            "route_id": route_id,
                            "operation": "SEARCH",
                            "reason_codes": ["REQUIRED"],
                            "search_spec": {
                                "mode": "INITIAL",
                                "constraints": [
                                    {"kind": "KEYWORD", "terms": ["Project"], "match_mode": "ANY"}
                                ],
                            },
                            "detail_candidate_ref": None,
                        }
                    ],
                    "required_information": ["ret-int-01-search-hit"],
                    "retrieval_order": [route_id],
                }
            )
        if prompt_id == "retrieval.select_evidence":
            segment_id = cast(list[dict[str, object]], prompt_input["ranked_segments"])[0][
                "segment_id"
            ]
            return _llm_result(
                {
                    "schema_version": 2,
                    "selected_segment_ids": [segment_id],
                    "evidence_drafts": [
                        {
                            "segment_id": segment_id,
                            "role": "SUPPORTS",
                            "relevance_reason": "ret-int-01-search-hit",
                        }
                    ],
                    "excluded_segment_ids": [],
                }
            )
        if prompt_id == "retrieval.assess_sufficiency":
            return _llm_result({"schema_version": 2, "status": "SUFFICIENT", "issues": []})
        raise AssertionError(f"unexpected prompt: {prompt_id}")


class _ChangedSearchLLM(_InitialSearchLLM):
    def __init__(self) -> None:
        super().__init__()
        self.planner_calls = 0
        self.sufficiency_calls = 0
        self.selection_calls = 0
        self.followup_input: Mapping[str, object] | None = None

    def invoke_structured(self, **kwargs: object) -> object:
        prompt_id = kwargs["prompt_ref"].prompt_id
        prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
        if prompt_id == "retrieval.plan_query":
            self.calls.append(dict(kwargs))
            self.planner_calls += 1
            route_id = cast(list[dict[str, object]], prompt_input["input_routes"])[0]["route_id"]
            if self.planner_calls == 1:
                return _llm_result(_search_plan(route_id, "INITIAL", "Project"))
            self.followup_input = prompt_input
            return _llm_result(_search_plan(route_id, "CHANGED", "Invoice"))
        if prompt_id == "retrieval.assess_sufficiency":
            self.calls.append(dict(kwargs))
            self.sufficiency_calls += 1
            if self.sufficiency_calls == 1:
                return _llm_result(
                    {
                        "schema_version": 2,
                        "status": "NEEDS_MORE_DATA",
                        "issues": [
                            {
                                "slot": "invoice",
                                "issue_type": "MISSING",
                                "required": True,
                                "resolution_source": "GOOGLE",
                                "safety_critical": False,
                                "reason_codes": ["ret-int-02"],
                            }
                        ],
                    }
                )
            return _llm_result({"schema_version": 2, "status": "SUFFICIENT", "issues": []})
        if prompt_id == "retrieval.select_evidence":
            self.calls.append(dict(kwargs))
            self.selection_calls += 1
            candidates = cast(list[dict[str, object]], prompt_input["ranked_segments"])
            segment_id = candidates[-1]["segment_id"]
            return _llm_result(
                {
                    "schema_version": 2,
                    "selected_segment_ids": [segment_id],
                    "evidence_drafts": [
                        {
                            "segment_id": segment_id,
                            "role": "SUPPORTS",
                            "relevance_reason": "ret-int-02-changed-hit",
                        }
                    ],
                    "excluded_segment_ids": [],
                }
            )
        return super().invoke_structured(**kwargs)


class _ExternalRetrievalRequiredLLM(_ChangedSearchLLM):
    """Round 1 is a clean SUFFICIENT (no Retrieval-local loop); the second
    ``retrieval.plan_query`` call is only reached via an external
    RetrievalRequiredV1 re-entry (Q2-HANDOFF), never Retrieval's own loop.
    That second call has no invocation-local prior canonical plan to merge
    against (a fresh subgraph invocation), so -- unlike the local-loop
    CHANGED SEARCH in ``_ChangedSearchLLM`` -- it must return INITIAL."""

    def invoke_structured(self, **kwargs: object) -> object:
        prompt_id = kwargs["prompt_ref"].prompt_id
        if prompt_id == "retrieval.plan_query":
            self.calls.append(dict(kwargs))
            self.planner_calls += 1
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            route_id = cast(list[dict[str, object]], prompt_input["input_routes"])[0]["route_id"]
            if self.planner_calls == 1:
                return _llm_result(_search_plan(route_id, "INITIAL", "Project"))
            self.followup_input = prompt_input
            return _llm_result(_search_plan(route_id, "INITIAL", "Invoice"))
        if prompt_id == "retrieval.assess_sufficiency":
            self.calls.append(dict(kwargs))
            self.sufficiency_calls += 1
            return _llm_result({"schema_version": 2, "status": "SUFFICIENT", "issues": []})
        return super().invoke_structured(**kwargs)


def _search_plan(route_id: object, mode: str, term: str) -> dict[str, object]:
    spec: dict[str, object] = {"mode": mode}
    if mode == "INITIAL":
        spec["constraints"] = [{"kind": "KEYWORD", "terms": [term], "match_mode": "ANY"}]
    else:
        spec["constraint_delta"] = {
            "upsert_constraints": [{"kind": "KEYWORD", "terms": [term], "match_mode": "ANY"}],
            "remove_constraint_kinds": [],
        }
    return {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": route_id,
                "operation": "SEARCH",
                "reason_codes": ["REQUIRED"],
                "search_spec": spec,
                "detail_candidate_ref": None,
            }
        ],
        "required_information": [term],
        "retrieval_order": [route_id],
    }


class _PagingGateway(FakeGoogleGateway):
    def search_gmail_threads(self, **kwargs: object) -> ResourcePage:
        page_token = cast(str | None, kwargs["page_token"])
        items = self._sorted_resources(ResourceType.GMAIL_THREAD)  # noqa: SLF001
        self.call_log.append(
            GoogleGatewayCallRecord("search_gmail_threads", dict(kwargs), True, False)
        )
        return ResourcePage(
            items=(items[0],) if page_token is None else (items[1],),
            next_page_token="opaque-ret-int-03" if page_token is None else None,
        )


class _NextPageLLM(_ChangedSearchLLM):
    def invoke_structured(self, **kwargs: object) -> object:
        if kwargs["prompt_ref"].prompt_id == "retrieval.plan_query" and self.planner_calls == 1:
            self.calls.append(dict(kwargs))
            self.planner_calls += 1
            prompt_input = cast(Mapping[str, object], kwargs["prompt_input"])
            route_id = cast(list[dict[str, object]], prompt_input["input_routes"])[0]["route_id"]
            self.followup_input = prompt_input
            return _llm_result(
                {
                    "schema_version": 2,
                    "route_queries": [
                        {
                            "route_id": route_id,
                            "operation": "NEXT_PAGE",
                            "reason_codes": ["MORE"],
                            "search_spec": None,
                            "detail_candidate_ref": None,
                        }
                    ],
                    "required_information": ["page2"],
                    "retrieval_order": [route_id],
                }
            )
        return super().invoke_structured(**kwargs)


def test_ret_int_01_initial_search_reaches_evidence_and_retrieval_result(tmp_path: Any) -> None:
    llm = _InitialSearchLLM()
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime_with_llm(
        database_path=_seed_runtime_database(tmp_path, status="ANALYZING"),
        llm_runtime=llm,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        id_prefix="ret-int-01",
    )
    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["requested_resource_hints"] = ["GMAIL_THREAD"]
        state["request_intent"]["meta"] = {"artifact_id": "intent-1", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        result = runtime._context_subgraph.invoke(routed)  # noqa: SLF001
        assert result["context_result"]["status"] == "SUFFICIENT"
        assert result["retrieval_result"] is not None
        assert [item.operation for item in gateway.call_log].count("search_gmail_threads") == 1
        assert any(call["prompt_ref"].prompt_id == "retrieval.plan_query" for call in llm.calls)
        assert result["context_result"]["evidence_drafts"]
    finally:
        runtime.close()


def test_ret_int_02_changed_search_reaches_second_round_evidence(tmp_path: Any) -> None:
    llm = _ChangedSearchLLM()
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime_with_llm(
        database_path=_seed_runtime_database(tmp_path, status="ANALYZING"),
        llm_runtime=llm,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        id_prefix="ret-int-02",
    )
    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["requested_resource_hints"] = ["GMAIL_THREAD"]
        state["request_intent"]["meta"] = {"artifact_id": "intent-2", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        result = runtime._context_subgraph.invoke(routed)  # noqa: SLF001
        assert llm.planner_calls == llm.sufficiency_calls == 2
        assert llm.followup_input is not None
        assert len(cast(list[object], llm.followup_input["prior_query_attempts"])) == 1
        assert result["retrieval_result"]["retrieval_rounds"] == 2
        assert [x.operation for x in gateway.call_log].count("search_gmail_threads") == 2
        assert "gmail_thread:thread-finance" in result["retrieval_result"]["source_resource_refs"]
    finally:
        runtime.close()


def test_ret_int_03_next_page_reaches_second_page_evidence(tmp_path: Any) -> None:
    llm = _NextPageLLM()
    gateway = _PagingGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime_with_llm(
        database_path=_seed_runtime_database(tmp_path, status="ANALYZING"),
        llm_runtime=llm,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        id_prefix="ret-int-03",
    )
    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["requested_resource_hints"] = ["GMAIL_THREAD"]
        state["request_intent"]["meta"] = {"artifact_id": "intent-3", "revision": 1, "based_on": []}
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        result = runtime._context_subgraph.invoke(routed)  # noqa: SLF001
        searches = [item for item in gateway.call_log if item.operation == "search_gmail_threads"]
        assert len(searches) == 2
        assert searches[0].arguments["page_token"] is None
        assert searches[1].arguments["page_token"] == "opaque-ret-int-03"
        assert llm.planner_calls == llm.sufficiency_calls == 2
        assert result["retrieval_result"]["retrieval_rounds"] == 2
        assert "gmail_thread:thread-finance" in result["retrieval_result"]["source_resource_refs"]
        assert llm.followup_input is not None
        assert "opaque-ret-int-03" not in repr(llm.followup_input)
        assert "opaque-ret-int-03" not in repr(result)
    finally:
        runtime.close()


def test_work_analysis_retrieval_required_reenters_retrieval_with_new_search(
    tmp_path: Any,
) -> None:
    """Q2-HANDOFF: an external RetrievalRequiredV1 signal (as Supervisor would
    build from WorkAnalysis NEEDS_MORE_DATA) makes Retrieval run a genuine new
    CHANGED SEARCH round, not just re-select evidence from the first round --
    and Retrieval's own local loop never produces this signal (round 1 here
    completes as a clean SUFFICIENT, no NEEDS_MORE_DATA involved)."""
    llm = _ExternalRetrievalRequiredLLM()
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    runtime = _make_runtime_with_llm(
        database_path=_seed_runtime_database(tmp_path, status="ANALYZING"),
        llm_runtime=llm,
        gateway=gateway,
        checkpoint_database_path=tmp_path / "checkpoints.db",
        prompt_manifest_path=_runtime_active_manifest_path(tmp_path),
        id_prefix="ret-required",
    )
    try:
        state = runtime._initial_state(_start_request())  # noqa: SLF001
        state["request_intent"] = _clear_intent()
        state["request_intent"]["requested_resource_hints"] = ["GMAIL_THREAD"]
        state["request_intent"]["meta"] = {
            "artifact_id": "intent-required",
            "revision": 1,
            "based_on": [],
        }
        routed = runtime._tool_route_subgraph.invoke(state)  # noqa: SLF001
        round_one = runtime._context_subgraph.invoke(routed)  # noqa: SLF001
        assert round_one["context_result"]["status"] == "SUFFICIENT"
        assert round_one["retrieval_result"]["retrieval_rounds"] == 1
        assert llm.planner_calls == llm.sufficiency_calls == 1
        assert [item.operation for item in gateway.call_log].count("search_gmail_threads") == 1

        round_one["workflow_signal"] = {
            "kind": "RETRIEVAL_REQUIRED",
            "reason_codes": ["WORK_ANALYSIS_NEEDS_MORE_DATA"],
            "needs": [
                {
                    "required_information": "Need the invoice total.",
                    "reason_codes": ["WORK_ANALYSIS_NEEDS_MORE_DATA"],
                }
            ],
        }
        result = runtime._context_subgraph.invoke(round_one)  # noqa: SLF001

        assert [item.operation for item in gateway.call_log].count("search_gmail_threads") == 2
        assert llm.planner_calls == 2
        assert llm.followup_input is not None
        issues = cast(list[dict[str, object]], llm.followup_input["unresolved_sufficiency_issues"])
        assert issues == [
            {
                "slot": "Need the invoice total.",
                "issue_type": "MISSING",
                "required": True,
                "resolution_source": "GOOGLE",
                "safety_critical": False,
                "reason_codes": ["WORK_ANALYSIS_NEEDS_MORE_DATA"],
            }
        ]
        assert result["retrieval_result"]["retrieval_rounds"] == 2
        assert "gmail_thread:thread-finance" in result["retrieval_result"]["source_resource_refs"]
        assert result["workflow_signal"] is None
    finally:
        runtime.close()
