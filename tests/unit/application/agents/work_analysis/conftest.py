from dataclasses import dataclass, field

from google_work_agent.ports.llm import (
    ActualRuntime,
    PromptReference,
    RequestedRuntimeMode,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


@dataclass
class FakeRuntime:
    output: object
    calls: list[dict[str, object]] = field(default_factory=list)

    def invoke_structured(self, **kwargs):
        self.calls.append(
            {"prompt_ref": kwargs["prompt_ref"], "prompt_input": dict(kwargs["prompt_input"])}
        )
        validator = kwargs.get("semantic_validate")
        if validator is not None:
            validator(self.output)
        return StructuredLLMResult(
            structured_output=self.output,
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
            provider_request_id="provider-1",
            safe_error_code=None,
        )


def prompt_ref(prompt_id: str, node_name: str) -> PromptReference:
    return PromptReference(
        prompt_bundle_version="test",
        prompt_id=prompt_id,
        prompt_version="1",
        content_hash="hash",
        agent_role="work_analysis",
        subgraph_name="work_analysis",
        node_name=node_name,
        node_state="INITIAL",
        purpose=node_name,
        input_schema_version="v1",
        output_schema_version="v1",
    )


TRACE = ObservabilityContext(
    request_id="req",
    command_id="cmd",
    conversation_id="conv",
    run_id="run",
    langgraph_thread_id="thread",
    llm_call_id="call",
)


def fact(fact_id: str, kind: str = "TASK") -> dict[str, object]:
    return {
        "fact_id": fact_id,
        "kind": kind,
        "subject": fact_id,
        "value": fact_id,
        "derivation": "EXPLICIT",
        "evidence_refs": ["ev-1"],
    }
