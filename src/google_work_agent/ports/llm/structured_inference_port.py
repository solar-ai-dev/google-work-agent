"""Product structured-inference runtime boundary."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)


@dataclass(frozen=True, slots=True)
class StructuredInferenceResultV1:
    schema_version: Literal[1]
    structured_output: dict[str, object]
    provider: str
    model: str
    actual_runtime: Literal["LOCAL_GPU", "API_LLM"]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fallback_reason: str | None


class StructuredInferencePort(Protocol):
    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
    ) -> StructuredInferenceResultV1: ...


__all__ = ["StructuredInferencePort", "StructuredInferenceResultV1"]
