"""Application decorator that fail-closes Product Prompt input drift before dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    FailureRecordValidationError,
    validate_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    PromptRuntimeInputContractError,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    PromptReference,
    ProviderResponsePayload,
    RuntimePolicy,
    StructuredLLMProvider,
    ToolCallingLLMProvider,
    ToolCallProviderResponse,
    ToolDefinition,
)


class _PromptInputValidator(Protocol):
    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None: ...


@dataclass(frozen=True, slots=True)
class PromptInputGuardedProvider:
    """Validate exact Product Prompt input and account the real dispatch.

    The same decorated provider instance is passed to schema/tool-call repair
    code, so primary, fallback, repair, tool-call, and tool-call-repair all
    cross this one boundary. ``account_provider_dispatch`` runs after local
    validation but immediately before the delegate invocation; a provider
    timeout/error therefore still consumes exactly one RunBudget call.
    """

    delegate: StructuredLLMProvider
    validator: _PromptInputValidator

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
        account_provider_dispatch()
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
        if not callable(getattr(delegate, "invoke_tool_call", None)):
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_MODE_BLOCKED,
                "selected provider does not support native tool calling",
            )
        account_provider_dispatch()
        return cast(ToolCallingLLMProvider, delegate).invoke_tool_call(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            tools=tools,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )

    def _validate(self, *, prompt_ref: PromptReference, prompt_input: Mapping[str, object]) -> None:
        try:
            self.validator.validate(
                prompt_id=prompt_ref.prompt_id,
                prompt_input=_base_projection_for_validation(
                    prompt_input,
                    prompt_id=prompt_ref.prompt_id,
                ),
            )
        except (PromptRuntimeInputContractError, FailureRecordValidationError) as error:
            # No dedicated public LLM error code exists for input-contract
            # violations. RUNTIME_VERSION_MISMATCH is the closest existing
            # fail-closed runtime-contract classification and avoids falsely
            # labelling this as a provider response failure.
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_VERSION_MISMATCH,
                f"prompt runtime input contract violation: {error}",
            ) from error


def _base_projection_for_validation(
    prompt_input: Mapping[str, object],
    *,
    prompt_id: str,
) -> Mapping[str, object]:
    """Validate revision metadata without widening the base input contract."""

    failure_record = prompt_input.get("failure_record")
    is_semantic_revision = (
        isinstance(failure_record, Mapping)
        and failure_record.get("experiment_disposition") == "RUN_REVISION"
    )
    if (
        not is_semantic_revision
        or prompt_id.endswith((".repair", ".revise", ".recheck"))
        or set(prompt_input)
        != {
            "base_projection",
            "candidate_output",
            "failure_record",
        }
    ):
        return prompt_input
    base_projection = prompt_input["base_projection"]
    if not isinstance(base_projection, Mapping):
        raise PromptRuntimeInputContractError("semantic revision base_projection must be an object")
    validate_failure_record_v1(prompt_input["failure_record"])
    return base_projection


__all__ = ["PromptInputGuardedProvider"]
