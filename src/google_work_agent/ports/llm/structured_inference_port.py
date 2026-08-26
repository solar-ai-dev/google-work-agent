"""Product structured-inference runtime boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from google_work_agent.ports.llm.contracts import (
    OutputSchemaDefinition,
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.observability_events import ObservabilityContext


class StructuredInferencePort(Protocol):
    """Select a runtime leaf and return one validated structured result."""

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult: ...


__all__ = ["StructuredInferencePort"]
