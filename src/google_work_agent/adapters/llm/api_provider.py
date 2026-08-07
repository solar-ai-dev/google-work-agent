"""API-backed structured provider boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from google_work_agent.ports import (
    ActualRuntime,
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    StructuredLLMProvider,
)


class APIProviderTransport(Protocol):
    """Transport boundary for a configurable external LLM provider."""

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        raise NotImplementedError

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
    ) -> ProviderResponsePayload:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ApiStructuredLLMProvider(StructuredLLMProvider):
    provider_name: str
    transport: APIProviderTransport
    model: str
    runtime: ActualRuntime = ActualRuntime.API_LLM

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
        payload = self.transport.invoke_structured(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            timeout_seconds=runtime_policy.api_timeout_seconds,
            api_key=api_key,
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
class APIProviderConnectionService:
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
