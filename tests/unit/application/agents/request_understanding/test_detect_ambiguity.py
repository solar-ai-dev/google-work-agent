from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    _validate_ambiguity,
    detect_ambiguity,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1


@dataclass
class FakeLLMRuntime:
    calls: list[dict[str, object]] = field(default_factory=list)

    def infer(
        self,
        requested_mode: RequestedModeV1,
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        del requested_mode, output_schema_ref
        self.calls.append({"prompt_ref": prompt_ref, "prompt_input": dict(input_projection)})
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output={
                "requires_confirmation": True,
                "reason_codes": ["MISSING_RECIPIENT"],
                "missing_fields": ["recipient"],
            },
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
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
        run_budget=cast(dict[str, Any], build_default_run_budget()),
        correlation=WorkflowCorrelationContext(
            request_id="request-1", command_id="command-1", api_contract_version="v1"
        ),
    )
    candidate: RequestGoalCandidateV1 = {
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


def test_detect_ambiguity_rejects_metadata_without_confirmation() -> None:
    with pytest.raises(ValueError, match="non-confirmation ambiguity metadata must be empty"):
        _validate_ambiguity(
            {
                "requires_confirmation": False,
                "reason_codes": ["MISSING_PROJECT_NAME"],
                "missing_fields": ["project_name"],
            }
        )
