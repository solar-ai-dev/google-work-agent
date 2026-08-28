from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from google_work_agent.application.agents.request_understanding.identify_goal import identify_goal
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    ActualRuntime,
    OutputSchemaDefinition,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


@dataclass
class FakeLLMRuntime:
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate=None,
    ) -> StructuredLLMResult:
        self.calls.append(
            {
                "prompt_ref": prompt_ref,
                "prompt_input": dict(prompt_input),
                "semantic_validate": semantic_validate,
            }
        )
        payload = {
            "schema_version": 2,
            "goal": "goal",
            "completion_conditions": ["done"],
            "constraints": [],
            "requested_effect_hints": ["READ"],
            "requested_resource_hints": ["GMAIL_THREAD"],
            "analysis_requirement": "REQUIRED",
            "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        }
        return StructuredLLMResult(
            structured_output=payload,
            provider="fake",
            model="fake",
            requested_mode=RequestedRuntimeMode.AUTO,
            actual_runtime=ActualRuntime.API_LLM,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            latency_ms=1,
            estimated_cost_usd=None,
            fallback_reason=None,
            structured_output_attempts=1,
            provider_request_id="provider-request-1",
            safe_error_code=None,
        )


def test_identify_goal__canonical_call__preserves_classify_prompt_contract() -> None:
    runtime = FakeLLMRuntime()
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="메일 찾아줘",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.classify",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="classify",
        node_state="INITIAL",
        purpose="classify",
        input_schema_version="v1",
        output_schema_version="v2",
    )
    candidate = identify_goal(llm_runtime=runtime, request=request, prompt_ref=prompt_ref)
    assert candidate["goal"] == "goal"
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "메일 찾아줘",
        "entry_mode": "AGENT_SEARCH",
        "language": None,
        "selected_resources": [],
    }
    assert runtime.calls[0]["prompt_ref"].prompt_id == "request_understanding.classify"
