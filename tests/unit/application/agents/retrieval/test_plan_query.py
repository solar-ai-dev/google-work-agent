from pathlib import Path
from typing import cast

import pytest
from tests.support.fakes.llm import FakeStructuredInferencePort

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.build_query import RouteConstraintPolicy
from google_work_agent.application.agents.retrieval.contracts.query_attempt import (
    QueryAttemptV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalV2ValidationError,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan_schema import (
    RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.retrieval.plan_query import (
    has_retrieval_followup_path,
    plan_query,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference


def _tool_route_plan(*, allowed_read_tool_ids: list[str]) -> ToolRoutePlanV2:
    return cast(
        ToolRoutePlanV2,
        {
            "schema_version": 2,
            "input_plan": {
                "schema_version": 1,
                "meta": {},
                "input_routes": [
                    {
                        "route_id": "route-1",
                        "resource_type": "GMAIL_THREAD",
                        "connector_id": "google_workspace",
                        "allowed_read_tool_ids": allowed_read_tool_ids,
                        "required": True,
                        "reason_codes": ["USER_REQUEST"],
                    }
                ],
            },
            "output_plan": {
                "schema_version": 1,
                "meta": {},
                "output_mode": "ANSWER",
            },
            "tool_registry_version": "test",
        },
    )


def test_retrieval_followup_path__rejects_exhausted_direct_selected_read() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["gmail_get_thread"]),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[],
        read_result_summaries=[],
        query_attempts=[],
    )


def test_retrieval_followup_path__allows_search_or_unread_page() -> None:
    assert has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(
            allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
        ),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
        read_result_summaries=[{"route_id": "route-1", "has_next_page": False, "result_count": 0}],
        query_attempts=[
            cast(
                QueryAttemptV1,
                {
                    "route_id": "route-1",
                    "operation_kind": "SEARCH",
                    "round_no": 0,
                    "normalized_intent_constraints": [
                        {
                            "kind": "KEYWORD",
                            "terms": ["회의 관련 메일"],
                            "match_mode": "PHRASE",
                        }
                    ],
                },
            )
        ],
    )
    assert has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["gmail_get_thread"]),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
        read_result_summaries=[{"route_id": "route-1", "has_next_page": True, "exhausted": False}],
        query_attempts=[],
    )


def test_retrieval_followup_path__does_not_expand_selected_detail_into_search() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(
            allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
        ),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[],
        read_result_summaries=[],
        query_attempts=[
            cast(
                QueryAttemptV1,
                {"route_id": "route-1", "operation_kind": "DETAIL_FETCH"},
            )
        ],
    )


def test_retrieval_followup_path__rejects_exhausted_identity_only_search() -> None:
    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": []}),
        tool_route_plan=_tool_route_plan(allowed_read_tool_ids=["tasks_list_tasks"]),
        route_policies={
            "route-1": RouteConstraintPolicy(
                frozenset({"CONTAINER_REF"}), frozenset({"CONTAINER_REF"})
            )
        },
        unresolved_sufficiency_issues=[],
        read_result_summaries=[{"has_next_page": False, "exhausted": True}],
        query_attempts=[cast(QueryAttemptV1, {"route_id": "route-1", "operation_kind": "SEARCH"})],
    )


@pytest.mark.parametrize(
    ("constraints", "search_attempt_count"),
    [
        ([{"kind": "RESOURCE", "field": "subject", "value": "정확한 제목"}], 1),
        ([], 2),
    ],
)
def test_retrieval_followup_path__does_not_broaden_exact_subject_or_repeat_expansion(
    constraints: list[dict[str, str]], search_attempt_count: int
) -> None:
    attempts = [
        cast(
            QueryAttemptV1,
            {
                "route_id": "route-1",
                "round_no": index,
                "operation_kind": "SEARCH",
                "normalized_intent_constraints": [
                    {
                        "kind": "KEYWORD",
                        "terms": ["회의 관련 메일"],
                        "match_mode": "PHRASE",
                    }
                ],
            },
        )
        for index in range(search_attempt_count)
    ]

    assert not has_retrieval_followup_path(
        request_intent=cast(RequestIntentV2, {"constraints": constraints}),
        tool_route_plan=_tool_route_plan(
            allowed_read_tool_ids=["gmail_search_threads", "gmail_get_thread"]
        ),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        unresolved_sufficiency_issues=[{"required": True, "resolution_source": "GOOGLE"}],
        read_result_summaries=[{"route_id": "route-1", "result_count": 0, "exhausted": True}],
        query_attempts=attempts,
    )


def test_plan_query_is__the_only_product_prompt__owner_in_retrieval_core() -> None:
    owner = (
        Path(__file__).resolve().parents[5] / "src/google_work_agent/application/agents/retrieval"
    )
    plan_source = (owner / "plan_query.py").read_text(encoding="utf-8")
    assert "StructuredInferencePort" in plan_source
    assert "PromptReference" in plan_source
    for operation in (
        "build_query.py",
        "execute_read.py",
        "normalize_segments.py",
        "resolve_availability.py",
        "rag_retrieve_rerank.py",
    ):
        source = (owner / operation).read_text(encoding="utf-8")
        assert "PromptReference" not in source
        assert "StructuredInferencePort" not in source


def test_selected_exact_resource__materializes_detail_fetch__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_thread"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
        retry_budget=build_default_run_budget(),
        validated_resource_refs={"route-1": ["gmail_thread:thread-42"]},
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["RESOURCE_SELECTED"],
            "search_spec": None,
            "detail_candidate_ref": "gmail_thread:thread-42",
        }
    ]


def test_followup_with_ranked_candidate__materializes_detail_fetch__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "current_round_no": 0,
            "unresolved_sufficiency_issues": [
                {
                    "required": True,
                    "resolution_source": "GOOGLE",
                    "reason_codes": ["INCOMPLETE"],
                }
            ],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
        detail_candidate_refs=[
            "gmail_thread:already-read",
            "gmail_thread:next-candidate",
        ],
        attempted_detail_candidate_refs=["gmail_thread:already-read"],
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": "DETAIL_FETCH",
            "reason_codes": ["CANDIDATE_DETAIL_REQUIRED"],
            "search_spec": None,
            "detail_candidate_ref": "gmail_thread:next-candidate",
        }
    ]


def test_followup_without_required_google_issue__keeps_query_planning_llm() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "NEXT_PAGE",
                "reason_codes": ["MORE_RESULTS_AVAILABLE"],
                "search_spec": None,
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["more candidates"],
        "retrieval_order": ["route-1"],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    _, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"current_round_no": 0, "unresolved_sufficiency_issues": []},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
        detail_candidate_refs=["gmail_thread:candidate"],
    )

    assert llm_invoked is True
    assert len(runtime.calls) == 1


def test_no_result_vague_phrase__relaxes_once__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    prior_attempt = cast(
        QueryAttemptV1,
        {
            "route_id": "route-1",
            "round_no": 0,
            "operation_kind": "SEARCH",
            "normalized_intent_constraints": [
                {
                    "kind": "KEYWORD",
                    "terms": ["회의 관련 메일"],
                    "match_mode": "PHRASE",
                }
            ],
        },
    )

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {"constraints": []},
            "current_round_no": 0,
            "prior_query_attempts": [prior_attempt],
            "unresolved_sufficiency_issues": [{"required": True, "resolution_source": "GOOGLE"}],
            "read_result_summaries": [
                {"route_id": "route-1", "result_count": 0, "exhausted": True}
            ],
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["route_queries"] == [
        {
            "route_id": "route-1",
            "operation": "SEARCH",
            "reason_codes": ["QUERY_RELAXED_AFTER_NO_RESULTS"],
            "search_spec": {
                "mode": "CHANGED",
                "constraint_delta": {
                    "upsert_constraints": [
                        {"kind": "KEYWORD", "terms": ["회의"], "match_mode": "ANY"}
                    ],
                    "remove_constraint_kinds": [],
                },
            },
            "detail_candidate_ref": None,
        }
    ]


def test_general_search__with_semantic_choice__keeps_query_planning_llm() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "KEYWORD", "terms": ["budget"], "match_mode": "ANY"}],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["matching threads"],
        "retrieval_order": ["route-1"],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    assert len(runtime.calls) == 1
    assert result == output
    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == ["KEYWORD"]
    assert projected_routes[0]["required_constraint_kinds"] == []


def test_initial_next_page__repairs_before_query_materialization() -> None:
    invalid_initial = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "NEXT_PAGE",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": None,
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["current tasks"],
        "retrieval_order": ["route-1"],
    }
    repaired = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [{"kind": "STATUS_SCOPE", "values": ["INCOMPLETE"]}],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["current tasks"],
        "retrieval_order": ["route-1"],
    }
    runtime = FakeStructuredInferencePort(outputs=[invalid_initial, repaired])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]

    result, budget, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"STATUS_SCOPE"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    assert result == repaired
    assert len(runtime.calls) == 2
    assert sum(budget["semantic_revisions_used_by_failure"].values()) == 1
    repair_input = cast(dict[str, object], runtime.calls[1]["prompt_input"])
    failure_record = cast(dict[str, object], repair_input["failure_record"])
    assert failure_record["failure_reason_code"] == "QUERY_OPERATION_FIELD_MISMATCH"
    assert failure_record["affected_field_paths"] == ["$.route_queries[].operation"]


def test_calendar_route__projects_existing__route_constraint_policy() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "calendar-read",
                "operation": "SEARCH",
                "reason_codes": ["POLICY_PRECONDITION"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "TEMPORAL_RANGE",
                            "axis": "EVENT_TIME",
                            "start_local": "2026-09-05T15:00:00",
                            "end_local": "2026-09-05T15:30:00",
                            "timezone": "Asia/Seoul",
                        }
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["calendar conflicts in requested window"],
        "retrieval_order": ["calendar-read"],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-read",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_PRECONDITION"],
        }
    ]

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes, "retrieval_budget": {}},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={
            "calendar-read": RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}))
        },
        retry_budget=build_default_run_budget(),
        validated_container_refs={"calendar-read": ["primary"]},
    )

    assert llm_invoked is True
    assert result == output
    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == [
        "CONTAINER_REF",
        "TEMPORAL_RANGE",
    ]
    assert projected_routes[0]["required_constraint_kinds"] == []


def test_exact_calendar_create_precondition__materializes_all_policy_reads__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-list",
            "resource_type": "CALENDAR",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_calendars"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "event-list",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "freebusy",
            "resource_type": "CALENDAR_FREEBUSY",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    ]
    policies = {
        route["route_id"]: RouteConstraintPolicy(
            frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}) if route["resource_type"] != "CALENDAR" else frozenset(),
        )
        for route in frozen_routes
    }
    container_refs = {route["route_id"]: ["primary"] for route in frozen_routes}

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["CALENDAR_EVENT"],
                "constraints": [
                    {"kind": "DATE", "field": "date", "value": "2026-09-05"},
                    {
                        "kind": "TIME",
                        "field": "start_time",
                        "value": "15:00",
                    },
                    {
                        "kind": "TIME",
                        "field": "end_time",
                        "value": "15:30",
                    },
                    {"kind": "TIME", "field": "timezone", "value": "Asia/Seoul"},
                ],
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["retrieval_order"] == ["calendar-list", "event-list", "freebusy"]
    assert [item["operation"] for item in result["route_queries"]] == [
        "SEARCH",
        "SEARCH",
        "FREEBUSY",
    ]
    for route_query in result["route_queries"]:
        search_spec = route_query["search_spec"]
        assert search_spec is not None
        assert search_spec["constraints"][0] == {
            "kind": "CONTAINER_REF",
            "container_refs": ["primary"],
        }
        assert search_spec["constraints"][1]["start_local"] == "2026-09-05T15:00:00"
        assert search_spec["constraints"][1]["end_local"] == "2026-09-05T15:30:00"


def test_exact_task_create_precondition__materializes_duplicate_reads__without_llm() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "tasks",
            "resource_type": "TASK",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasks"],
            "required": True,
            "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        },
        {
            "route_id": "task-lists",
            "resource_type": "TASK_LIST",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["tasks_list_tasklists"],
            "required": True,
            "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
        },
    ]
    policies = {
        route["route_id"]: RouteConstraintPolicy(
            frozenset({"CONTAINER_REF"}),
            frozenset({"CONTAINER_REF"}) if route["resource_type"] == "TASK" else frozenset(),
        )
        for route in frozen_routes
    }
    container_refs = {route["route_id"]: ["@default"] for route in frozen_routes}

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={
            "request_intent": {
                "requested_effect_hints": ["CREATE"],
                "requested_resource_hints": ["TASK"],
                "constraints": [{"kind": "RESOURCE", "field": "title", "value": "Submit report"}],
            },
            "input_routes": frozen_routes,
        },
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies=policies,
        retry_budget=build_default_run_budget(),
        validated_container_refs=container_refs,
    )

    assert llm_invoked is False
    assert runtime.calls == []
    assert result["retrieval_order"] == ["tasks", "task-lists"]
    assert [item["operation"] for item in result["route_queries"]] == [
        "SEARCH",
        "SEARCH",
    ]
    for route_query in result["route_queries"]:
        assert route_query["search_spec"] == {
            "mode": "INITIAL",
            "constraints": [{"kind": "CONTAINER_REF", "container_refs": ["@default"]}],
        }


def test_calendar_route__without_validated_container__does_not_offer_container_ref() -> None:
    runtime = FakeStructuredInferencePort(
        outputs=[
            {
                "schema_version": 2,
                "route_queries": [
                    {
                        "route_id": "calendar-read",
                        "operation": "SEARCH",
                        "reason_codes": ["POLICY_PRECONDITION"],
                        "search_spec": {
                            "mode": "INITIAL",
                            "constraints": [
                                {
                                    "kind": "TEMPORAL_RANGE",
                                    "axis": "EVENT_TIME",
                                    "start_local": "2026-09-05T15:00:00",
                                    "end_local": "2026-09-05T15:30:00",
                                    "timezone": "Asia/Seoul",
                                }
                            ],
                        },
                        "detail_candidate_ref": None,
                    }
                ],
                "required_information": ["calendar conflicts"],
                "retrieval_order": ["calendar-read"],
            }
        ]
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "calendar-read",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_PRECONDITION"],
        }
    ]

    plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input={"request_intent": {}, "input_routes": frozen_routes},
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={
            "calendar-read": RouteConstraintPolicy(frozenset({"TEMPORAL_RANGE", "CONTAINER_REF"}))
        },
        retry_budget=build_default_run_budget(),
    )

    projected_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    projected_routes = cast(list[dict[str, object]], projected_input["input_routes"])
    assert projected_routes[0]["supported_constraint_kinds"] == ["TEMPORAL_RANGE"]


def test_general_gmail_search__preserves_explicit__sender_subject_values() -> None:
    output = {
        "schema_version": 2,
        "route_queries": [
            {
                "route_id": "route-1",
                "operation": "SEARCH",
                "reason_codes": ["USER_REQUEST"],
                "search_spec": {
                    "mode": "INITIAL",
                    "constraints": [
                        {
                            "kind": "PARTICIPANT",
                            "participants": [{"role": "SENDER", "identity": "wrong@example.com"}],
                            "match_mode": "ALL",
                        },
                        {"kind": "KEYWORD", "terms": ["corrupted"], "match_mode": "PHRASE"},
                    ],
                },
                "detail_candidate_ref": None,
            }
        ],
        "required_information": ["matching threads"],
        "retrieval_order": ["route-1"],
    }
    runtime = FakeStructuredInferencePort(outputs=[output])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
            "required": True,
            "reason_codes": ["USER_REQUEST"],
        }
    ]
    prompt_input = {
        "request_intent": {
            "constraints": [
                {
                    "kind": "SCOPE",
                    "field": "search_criteria_sender",
                    "value": "sender@example.com",
                },
                {"kind": "SCOPE", "field": "search_criteria_subject", "value": "회신부탁"},
            ]
        },
        "input_routes": frozen_routes,
    }

    result, _, llm_invoked = plan_query(
        llm_runtime=runtime,
        prompt_ref=prompt_ref,
        revision_prompt_ref=prompt_ref,
        output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
        prompt_input=prompt_input,
        requested_mode="LOCAL_GPU",
        frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
        route_policies={"route-1": RouteConstraintPolicy(frozenset({"PARTICIPANT", "KEYWORD"}))},
        retry_budget=build_default_run_budget(),
    )

    assert llm_invoked is True
    constraints = result["route_queries"][0]["search_spec"]
    assert constraints is not None
    assert constraints["constraints"] == [
        {
            "kind": "PARTICIPANT",
            "participants": [{"role": "SENDER", "identity": "sender@example.com"}],
            "match_mode": "ALL",
        },
        {"kind": "KEYWORD", "terms": ["회신부탁"], "match_mode": "PHRASE"},
    ]


def test_selected_exact_resource__invalid_route_binding__fails_without_llm_fallback() -> None:
    runtime = FakeStructuredInferencePort(outputs=[])
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="retrieval.plan_query",
        prompt_version="1",
        content_hash="hash",
        agent_role="retrieval",
        subgraph_name="retrieval",
        node_name="plan_query",
        node_state="INITIAL",
        purpose="plan_query",
        input_schema_version="v2",
        output_schema_version="v2",
    )
    frozen_routes = [
        {
            "route_id": "route-1",
            "resource_type": "GMAIL_THREAD",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail_get_thread"],
            "required": True,
            "reason_codes": ["RESOURCE_SELECTED"],
        }
    ]

    with pytest.raises(RetrievalV2ValidationError, match="does not match"):
        plan_query(
            llm_runtime=runtime,
            prompt_ref=prompt_ref,
            revision_prompt_ref=prompt_ref,
            output_schema=RETRIEVAL_QUERY_PLAN_V2_OUTPUT_SCHEMA,
            prompt_input={"request_intent": {}, "input_routes": frozen_routes},
            requested_mode="LOCAL_GPU",
            frozen_routes=cast(list[InputToolRouteV1], frozen_routes),
            route_policies={"route-1": RouteConstraintPolicy(frozenset({"RESOURCE_REF"}))},
            retry_budget=build_default_run_budget(),
            validated_resource_refs={"route-1": ["task:wrong-scope"]},
        )

    assert runtime.calls == []
