from collections import deque
from dataclasses import replace

from tests.unit.application.workflows.test_context_retrieval import (
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
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def test_assess_sufficiency_emits_a_typed_bounded_disposition() -> None:
    runtime = FakeLLMRuntime(deque([_llm_result(_sufficiency_output("SUFFICIENT"))]))
    result = assess_sufficiency(
        llm_runtime=runtime,
        prompt_ref=replace(SUFFICIENCY_PROMPT_REF, prompt_id="retrieval.assess_sufficiency"),
        trace_context=ObservabilityContext(
            request_id="request-1",
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            langgraph_thread_id="thread-1",
            llm_call_id="run-1:retrieval.assess_sufficiency",
        ),
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
    assert "confirmation_response" not in runtime.calls[0]["prompt_input"]
    assert set(runtime.calls[0]["prompt_input"]) == {
        "request_intent",
        "selected_evidence",
        "source_statuses",
        "budget_state",
    }
