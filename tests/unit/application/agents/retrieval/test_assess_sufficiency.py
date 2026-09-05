from collections import deque
from dataclasses import replace
from typing import cast

import pytest
from tests.support.context_retrieval import (
    SUFFICIENCY_PROMPT_REF,
    FakeLLMRuntime,
    _acquisition_result,
    _intent,
    _llm_result,
    _run_budget,
    _sufficiency_output,
    _tool_route_plan,
)

from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    assess_sufficiency,
    authorize_retrieval_followup,
)


def test_assess_sufficiency__emits_a__typed_bounded_disposition() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=replace(SUFFICIENCY_PROMPT_REF, prompt_id="retrieval.assess_sufficiency"),
        requested_mode="AUTO",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-segment-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "Project Alpha update",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "SUFFICIENT"
    prompt_input = cast(dict[str, object], runtime.calls[0]["prompt_input"])
    assert "confirmation_response" not in prompt_input
    assert set(prompt_input) == {
        "request_intent",
        "selected_evidence",
        "source_statuses",
        "budget_state",
    }


def test_retrieval_followup__charges_one_additional_round_before_reentry() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=True,
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert budget["additional_retrieval_rounds_used"] == 1
    assert should_retrieve_more is True


def test_retrieval_followup__normalizes_exhausted_read_with_evidence_to_partial() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=2),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=True,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 2
    assert should_retrieve_more is False


def test_retrieval_followup__closes_selected_direct_read_without_new_path() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=0),
        evidence_supported_partial_possible=True,
        can_acquire_new_information=False,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 0
    assert should_retrieve_more is False


def test_retrieval_followup__closes_empty_read_without_user_confirmation() -> None:
    result, budget, should_retrieve_more = authorize_retrieval_followup(
        _sufficiency_output("NEEDS_MORE_DATA"),
        request_intent=_intent(),
        retry_budget=_run_budget(used=1),
        evidence_supported_partial_possible=False,
        can_acquire_new_information=False,
    )

    assert result["status"] == "PARTIAL"
    assert budget["additional_retrieval_rounds_used"] == 1
    assert should_retrieve_more is False


def test_assess_sufficiency__complete_selected_gmail_read__skips_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["analysis_requirement"] = "NONE"
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_get_thread"],
                "required": True,
                "reason_codes": ["RESOURCE_SELECTED"],
            }
        ]
    )

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-segment-1",
                "resource_handle": "gmail_thread:thread-kim",
                "segment_id": "segment-1",
                "kind": "excerpt",
                "excerpt": "From: Kim\nSubject: Project\nPlease reply next week.",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    assert runtime.calls == []


@pytest.mark.parametrize("resource", ["TASK", "CALENDAR_EVENT"])
@pytest.mark.parametrize("incomplete", [None, "failed_route", "missing_route", "source_request"])
def test_assess_sufficiency__only_complete_create_policy_reads__skip_llm(
    resource: str, incomplete: str | None,
) -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["requested_effect_hints"] = ["CREATE"]
    intent["requested_resource_hints"] = [resource]
    intent["analysis_requirement"] = "NONE"
    routes = [
        {
            "route_id": "calendar-route",
            "resource_type": "CALENDAR",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_calendars"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "events-route",
            "resource_type": "CALENDAR_EVENT",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_list_events"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
        {
            "route_id": "freebusy-route",
            "resource_type": "CALENDAR_FREEBUSY",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["calendar_query_freebusy"],
            "required": True,
            "reason_codes": ["POLICY_CALENDAR_CONFLICT_CHECK"],
        },
    ]
    if resource == "TASK":
        routes = [
            {
                "route_id": "task-route", "resource_type": "TASK",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasks"],
                "required": True, "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
            {
                "route_id": "list-route", "resource_type": "TASK_LIST",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["tasks_list_tasklists"],
                "required": True, "reason_codes": ["POLICY_TASK_DUPLICATE_CHECK"],
            },
        ]
    route_plan = _tool_route_plan(routes)
    route_plan["output_plan"] = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "create-route",
                "resource_type": resource,
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "selected_tool_id": (
                    "tasks_create_task" if resource == "TASK" else "calendar_create_event"
                ),
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ],
    }
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = ["calendar:primary", "calendar_freebusy:primary:hash"]
    acquisition["source_summaries"] = [
        {
            "route_id": route["route_id"],
            "source": "TASKS" if resource == "TASK" else "CALENDAR",
            "status": "COMPLETE",
            "required": True,
            "resource_count": 0 if route["resource_type"] == "CALENDAR_EVENT" else 1,
            "resource_handles": [],
            "resources": [],
        }
        for route in routes
    ]

    if incomplete == "failed_route":
        acquisition["source_summaries"][0]["status"] = "FAILED"
    elif incomplete == "missing_route":
        acquisition["source_summaries"].pop()
    elif incomplete == "source_request":
        route_plan["input_plan"]["input_routes"][0]["reason_codes"] = ["USER_REQUESTED"]

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    if incomplete is None:
        assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
        assert runtime.calls == []
    else:
        assert result["status"] != "SUFFICIENT"
        assert len(runtime.calls) == 1


def test_assess_sufficiency__rejects_required_lookup__without_evidence() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    acquisition = _acquisition_result()

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == [
        "REQUIRED_SOURCE_RETURNED_NO_RESOURCES"
    ]


def test_mail_to_task__does_not_replace_empty_mail_with_task_policy_evidence() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    acquisition = _acquisition_result()
    acquisition["source_summaries"][0]["resource_count"] = 0
    acquisition["source_summaries"][0]["resource_handles"] = []
    acquisition["resource_handles"] = ["task:existing"]
    intent = _intent()
    intent["requested_effect_hints"] = ["READ", "CREATE"]
    result = assess_sufficiency(
        llm_runtime=runtime, prompt_ref=SUFFICIENCY_PROMPT_REF, requested_mode="LOCAL_GPU",
        request_intent=intent, tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[{
            "schema_version": 1, "evidence_id": "e-task", "resource_handle": "task:existing",
            "segment_id": "s-task", "kind": "excerpt", "excerpt": "기존 태스크",
            "locator": {}, "reason_codes": ["SUPPORTS"],
        }],
        retry_budget=_run_budget(used=0),
    )
    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == ["REQUIRED_SOURCE_RETURNED_NO_RESOURCES"]


def test_assess_sufficiency__requires_each_selected_gmail_thread_detail_for_analysis() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )
    evidence = [
        {
            "schema_version": 1,
            "evidence_id": f"evidence-{name}",
            "resource_handle": f"gmail_thread:{name}",
            "segment_id": f"segment-{name}",
            "kind": "excerpt",
            "excerpt": f"KAN-93 {name}",
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        }
        for name in ("first", "second")
    ]

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=0),
        attempted_detail_candidate_refs=["gmail_thread:first"],
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]


def test_assess_sufficiency__read_only_google_gap__cannot_block_candidate_detail() -> None:
    blocked_google_gap = {
        "schema_version": 2,
        "status": "BLOCKED",
        "issues": [
            {
                "slot": "latest_decision",
                "issue_type": "MISSING",
                "required": True,
                "resolution_source": "GOOGLE",
                "safety_critical": True,
                "reason_codes": ["CONTENT_NOT_EXPOSED"],
            }
        ],
    }
    runtime = FakeLLMRuntime(deque([_llm_result(blocked_google_gap)]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=[
            {
                "schema_version": 1,
                "evidence_id": "evidence-first",
                "resource_handle": "gmail_thread:first",
                "segment_id": "segment-first",
                "kind": "excerpt",
                "excerpt": "KAN-93 metadata",
                "locator": {},
                "reason_codes": ["SUPPORTS"],
            }
        ],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert result["issues"][-1]["reason_codes"] == ["CANDIDATE_DETAIL_REQUIRED"]


def test_assess_sufficiency__accepts_analysis_after_all_candidate_details() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    intent = _intent()
    intent["analysis_requirement"] = "REQUIRED"
    intent["requested_effect_hints"] = ["READ"]
    intent["requested_resource_hints"] = ["GMAIL_THREAD"]
    route_plan = _tool_route_plan(
        [
            {
                "route_id": "route-gmail",
                "resource_type": "GMAIL_THREAD",
                "connector_id": "google_workspace",
                "allowed_read_tool_ids": ["gmail_search_threads", "gmail_get_thread"],
                "required": True,
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ]
    )
    evidence = [
        {
            "schema_version": 1,
            "evidence_id": f"evidence-{name}",
            "resource_handle": f"gmail_thread:{name}",
            "segment_id": f"segment-{name}",
            "kind": "excerpt",
            "excerpt": f"KAN-93 {name}",
            "locator": {},
            "reason_codes": ["SUPPORTS"],
        }
        for name in ("first", "second")
    ]

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=intent,
        tool_route_plan=route_plan,
        acquisition_result=_acquisition_result(),
        evidence_drafts=evidence,
        retry_budget=_run_budget(used=0),
        attempted_detail_candidate_refs=["gmail_thread:first", "gmail_thread:second"],
    )

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}


def test_assess_sufficiency__read_only_connector_gap__cannot_become_user_confirmation() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("NEEDS_CONFIRMATION"))]))
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = []
    acquisition["source_summaries"][0]["resource_count"] = 0
    acquisition["source_summaries"][0]["resource_handles"] = []

    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=SUFFICIENCY_PROMPT_REF,
        requested_mode="LOCAL_GPU",
        request_intent=_intent(),
        tool_route_plan=_tool_route_plan(),
        acquisition_result=acquisition,
        evidence_drafts=[],
        retry_budget=_run_budget(used=0),
    )

    assert result["status"] == "NEEDS_MORE_DATA"
    assert {issue["resolution_source"] for issue in result["issues"]} == {"GOOGLE"}
