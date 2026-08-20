"""Provider decorator that fail-closes Product Prompt input drift before dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from google_work_agent.application.workflows.prompt_input_contract import (
    PromptInputContractError,
    PromptRuntimeInputContractValidator,
)
from google_work_agent.ports import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    ToolCallProviderResponse,
    ToolDefinition,
)


class _StructuredProvider(Protocol):
    provider_name: str
    runtime: ActualRuntime

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload: ...


class _ToolCallingProvider(Protocol):
    provider_name: str
    runtime: ActualRuntime

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ToolCallProviderResponse: ...


@runtime_checkable
class _RuntimeToolCallingProvider(_ToolCallingProvider, Protocol):
    pass


@dataclass(frozen=True, slots=True)
class PromptInputGuardedProvider:
    """Validate the exact projection immediately before every provider call.

    The same decorated provider instance is passed to schema-repair code, so
    repair/revision calls are checked against their own registered PromptRef
    as well; there is no alternate unvalidated repair dispatch path.
    """

    delegate: _StructuredProvider
    validator: PromptRuntimeInputContractValidator

    @property
    def provider_name(self) -> str:
        return self.delegate.provider_name

    @property
    def runtime(self) -> ActualRuntime:
        return self.delegate.runtime

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload:
        self._validate(prompt_ref=prompt_ref, prompt_input=prompt_input)
        return self.delegate.invoke_structured(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ToolCallProviderResponse:
        self._validate(prompt_ref=prompt_ref, prompt_input=prompt_input)
        delegate = self.delegate
        if not isinstance(delegate, _RuntimeToolCallingProvider):
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_MODE_BLOCKED,
                "selected provider does not support native tool calling",
            )
        return delegate.invoke_tool_call(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            tools=tools,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )

    def _validate(
        self, *, prompt_ref: PromptReference, prompt_input: Mapping[str, object]
    ) -> None:
        try:
            self.validator.validate(prompt_id=prompt_ref.prompt_id, prompt_input=prompt_input)
        except PromptInputContractError as error:
            # No dedicated public LLM error code exists for input-contract
            # violations. RUNTIME_VERSION_MISMATCH is the closest existing
            # fail-closed runtime-contract classification and avoids falsely
            # labelling this as a provider response failure.
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_VERSION_MISMATCH,
                f"prompt runtime input contract violation: {error}",
            ) from error


__all__ = ["PromptInputGuardedProvider"]
