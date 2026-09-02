from collections.abc import Mapping, Sequence

from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaTransport
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    ToolCallProviderResponse,
    ToolDefinition,
)


class _Transport(OllamaTransport):
    def probe(self, *, endpoint: str, model_id: str | None, timeout_seconds: int) -> ProbeResult:
        del endpoint, model_id, timeout_seconds
        raise AssertionError("probe is outside this structured-inference test")

    def invoke_structured(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ProviderResponsePayload:
        del (
            prompt_ref,
            prompt_input,
            output_schema,
            timeout_seconds,
            instruction_text,
            sampling_temperature,
            sampling_seed,
        )
        assert endpoint == "http://127.0.0.1:11434"
        assert model_id == "model-1"
        return ProviderResponsePayload({}, "model-1", None, 1, 1, 1)

    def invoke_tool_call(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        timeout_seconds: int,
        instruction_text: str,
        sampling_temperature: float | None = None,
        sampling_seed: int | None = None,
    ) -> ToolCallProviderResponse:
        del (
            endpoint,
            model_id,
            prompt_ref,
            prompt_input,
            tools,
            timeout_seconds,
            instruction_text,
            sampling_temperature,
            sampling_seed,
        )
        raise AssertionError("tool calling is outside this structured-inference test")


def test_ollama_leaf__dispatches_only_to__configured_local_transport() -> None:
    adapter = OllamaStructuredInferenceAdapter(
        "ollama", _Transport(), "http://127.0.0.1:11434", "model-1"
    )

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
