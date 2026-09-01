from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1


@dataclass
class WorkAnalysisRuntimeFake:
    output: object
    calls: list[dict[str, object]] = field(default_factory=list)

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1:
        self.calls.append(
            {
                "requested_mode": requested_mode,
                "prompt_ref": prompt_ref,
                "prompt_input": dict(input_projection),
                "output_schema": output_schema_ref,
            }
        )
        return StructuredInferenceResultV1(
            schema_version=1,
            structured_output=cast(dict[str, object], self.output),
            provider="fake",
            model="fake",
            actual_runtime="API_LLM",
            input_tokens=1,
            output_tokens=1,
            latency_ms=1,
            fallback_reason=None,
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


def fact(
    fact_id: str,
    kind: Literal[
        "TASK",
        "EVENT",
        "PERSON",
        "DATE",
        "TIME",
        "DEADLINE",
        "STATUS",
        "RESOURCE",
        "TEXT_CLAIM",
        "OTHER",
    ] = "TASK",
) -> WorkFactV1:
    return {
        "fact_id": fact_id,
        "kind": kind,
        "subject": fact_id,
        "value": fact_id,
        "derivation": "EXPLICIT",
        "evidence_refs": ["ev-1"],
    }


def intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "complete the requested work",
        "completion_conditions": ["work completed"],
        "constraints": [],
        "requested_effect_hints": [],
        "requested_resource_hints": [],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
