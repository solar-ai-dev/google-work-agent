from typing import Any

from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


class _Transport:
    def invoke_structured(self, **kwargs: Any) -> ProviderResponsePayload:
        assert kwargs["endpoint"] == "http://127.0.0.1:11434"
        assert kwargs["model_id"] == "model-1"
        return ProviderResponsePayload({}, "model-1", None, 1, 1, 1)


def test_ollama_leaf_dispatches_only_to_configured_local_transport() -> None:
    adapter = OllamaStructuredInferenceAdapter(
        "ollama", _Transport(), "http://127.0.0.1:11434", "model-1"
    )  # type: ignore[arg-type]

    result = adapter.invoke_structured(
        prompt_ref=_prompt(),
        prompt_input={},
        output_schema=OutputSchemaDefinition("v1", {"type": "object"}),
        runtime_policy=RuntimePolicy(),
        api_key=None,
    )

    assert result.model == "model-1"


def _prompt() -> PromptReference:
    return PromptReference("b", "p", "1", "h", "r", "s", "n", "x", "test", "v1", "v1")
