from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)
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
        self.calls.append({"prompt_ref": prompt_ref, "prompt_input": dict(prompt_input)})
        return StructuredLLMResult(
            structured_output={
                "requires_confirmation": True,
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            },
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


def test_detect_ambiguity__canonical_call__owns_independent_ambiguity() -> None:
    runtime = FakeLLMRuntime()
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="일정을 잡아줘",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    candidate = {
        "goal": "일정 만들기",
        "completion_conditions": ["일정을 만든다"],
        "constraints": [],
        "requested_effect_hints": ["CREATE"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "REQUIRED",
    }
    prompt_ref = PromptReference(
        prompt_bundle_version="test",
        prompt_id="request_understanding.detect_ambiguity",
        prompt_version="1",
        content_hash="hash",
        agent_role="request_understanding",
        subgraph_name="request_understanding",
        node_name="detect_ambiguity",
        node_state="INITIAL",
        purpose="detect_ambiguity",
        input_schema_version="v1",
        output_schema_version="v1",
    )

    result = detect_ambiguity(
        llm_runtime=runtime,
        request=request,
        goal_candidate=candidate,
        prompt_ref=prompt_ref,
    )

    assert result["requires_confirmation"] is True
    assert runtime.calls[0]["prompt_input"] == {
        "user_request": "일정을 잡아줘",
        "goal_candidate": candidate,
    }
