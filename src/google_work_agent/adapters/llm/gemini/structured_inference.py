"""API-backed structured provider boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from google_work_agent.ports import (
    ActualRuntime,
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
)


class APIProviderTransport(Protocol):
    """Transport boundary for a configurable external LLM provider."""

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        raise NotImplementedError

    def invoke_structured(
        self,
        *,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
        instruction_text: str,
        sampling_temperature: float | None = None,
    ) -> ProviderResponsePayload:
        raise NotImplementedError


def _no_instruction_text(prompt_ref: PromptReference) -> str:
    del prompt_ref
    return ""


@dataclass(frozen=True, slots=True)
class GeminiStructuredInferenceAdapter:
    """Dispatches one structured external-API call.

    Structurally satisfies ``StructuredLLMProvider`` (not a nominal base
    class: subclassing a ``Protocol`` here would make its members real
    inherited descriptors, which collides with this dataclass's own field
    ordering).

    ``resolve_instruction_text`` is called here, immediately before dispatch,
    and its result lives only as a local variable for the duration of this
    call -- mirrors ``OllamaStructuredLLMProvider`` so the assembled prompt
    text never reaches ``prompt_ref``/Trace/Checkpoint storage (see
    docs/00-CODE-AGENT-START-HERE.md section 4).
    """

    provider_name: str
    transport: APIProviderTransport
    model: str
    runtime: ActualRuntime = ActualRuntime.API_LLM
    resolve_instruction_text: Callable[[PromptReference], str] = field(default=_no_instruction_text)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        if not api_key:
            raise ValueError("API key is required")
        instruction_text = self.resolve_instruction_text(prompt_ref)
        # docs/15 section 9.5 (Runtime Prompt Activation Gate): only
        # sampling_temperature is forwarded here. runtime_policy.sampling_seed
        # is intentionally NOT passed to this transport -- this repository's
        # Gemini adapter contract (adapters/llm/gemini.py) does not confirm
        # seed support in the generateContent API it calls, and an
        # unconfirmed field must not be sent (see docs/15 section 9.5).
        payload = self.transport.invoke_structured(
            model_id=self.model,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            timeout_seconds=runtime_policy.api_timeout_seconds,
            api_key=api_key,
            instruction_text=instruction_text,
            sampling_temperature=runtime_policy.sampling_temperature,
        )
        return ProviderResponsePayload(
            content=payload.content,
            model=payload.model or self.model,
            provider_request_id=payload.provider_request_id,
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            latency_ms=payload.latency_ms,
            estimated_cost_usd=payload.estimated_cost_usd,
        )


@dataclass(frozen=True, slots=True)
class GeminiConnectionService:
    transport: APIProviderTransport | None

    def probe(self, *, api_key: str | None, timeout_seconds: int) -> ProbeResult:
        if self.transport is None:
            return ProbeResult(
                availability=AvailabilityState.NOT_CONFIGURED,
                safe_error_code="API_PROVIDER_NOT_CONFIGURED",
            )
        if not api_key:
            return ProbeResult(
                availability=AvailabilityState.NOT_CONFIGURED,
                safe_error_code="API_KEY_MISSING",
            )
        return self.transport.probe(api_key=api_key, timeout_seconds=timeout_seconds)
