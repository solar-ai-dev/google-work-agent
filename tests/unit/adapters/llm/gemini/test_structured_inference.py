from typing import Any

from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


class _Transport:
    def invoke_structured(self, **kwargs: Any) -> ProviderResponsePayload:
        assert kwargs["api_key"] == "secret"
        return ProviderResponsePayload({}, "", "request-1", 1, 2, 3)


def test_gemini_leaf_dispatches_structured_inference() -> None:
    adapter = GeminiStructuredInferenceAdapter("gemini", _Transport(), "model-1")  # type: ignore[arg-type]

    result = adapter.invoke_structured(
        prompt_ref=_prompt(),
        prompt_input={},
        output_schema=OutputSchemaDefinition("v1", {"type": "object"}),
        runtime_policy=RuntimePolicy(),
        api_key="secret",
    )

    assert result.model == "model-1"


def _prompt() -> PromptReference:
    return PromptReference("b", "p", "1", "h", "r", "s", "n", "x", "test", "v1", "v1")
