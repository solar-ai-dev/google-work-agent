from collections import deque
from dataclasses import replace
from typing import cast

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


def test_assess_sufficiency__complete_calendar_policy_reads__skip_llm() -> None:
    runtime = FakeLLMRuntime()
    intent = _intent()
    intent["requested_effect_hints"] = ["CREATE"]
    intent["requested_resource_hints"] = ["CALENDAR_EVENT"]
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
    route_plan = _tool_route_plan(routes)
    route_plan["output_plan"] = {
        "schema_version": 1,
        "meta": {"artifact_id": "route-out-1", "revision": 1, "based_on": []},
        "output_mode": "ACTION",
        "output_routes": [
            {
                "route_id": "create-route",
                "resource_type": "CALENDAR_EVENT",
                "connector_id": "google_workspace",
                "effect": "CREATE",
                "selected_tool_id": "calendar_create_event",
                "reason_codes": ["REGISTRY_SINGLE_CANDIDATE"],
            }
        ],
    }
    acquisition = _acquisition_result()
    acquisition["resource_handles"] = ["calendar:primary", "calendar_freebusy:primary:hash"]
    acquisition["source_summaries"] = [
        {
            "route_id": route["route_id"],
            "source": "CALENDAR",
            "status": "COMPLETE",
            "required": True,
            "resource_count": 0 if route["resource_type"] == "CALENDAR_EVENT" else 1,
            "resource_handles": [],
            "resources": [],
        }
        for route in routes
    ]

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

    assert result == {"schema_version": 2, "status": "SUFFICIENT", "issues": []}
    assert runtime.calls == []


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
