"""Application decorator that fail-closes Product Prompt input drift before dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from google_work_agent.application.orchestration.failure_record import (
    FAILURE_RECORD_FIELDS,
    FailureRecordValidationError,
    build_failure_record_v1,
    validate_failure_record_v1,
)
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    account_provider_dispatch,
)
from google_work_agent.application.prompt_runtime.contracts.prompt_runtime_input_contract import (
    PromptRuntimeInputContractError,
)
from google_work_agent.ports.llm import (
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
    @property
    def provider_name(self) -> str: ...
    @property
    def runtime(self) -> ActualRuntime: ...

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
    ) -> ProviderResponsePayload: ...


class _PromptInputValidator(Protocol):
    def validate(self, *, prompt_id: str, prompt_input: Mapping[str, object]) -> None: ...


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
    """Validate exact Product Prompt input and account the real dispatch.

    The same decorated provider instance is passed to schema/tool-call repair
    code, so primary, fallback, repair, tool-call, and tool-call-repair all
    cross this one boundary. ``account_provider_dispatch`` runs after local
    validation but immediately before the delegate invocation; a provider
    timeout/error therefore still consumes exactly one RunBudget call.
    """

    delegate: _StructuredProvider
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
        normalized_input = _canonical_prompt_input(prompt_input)
        self._validate(prompt_ref=prompt_ref, prompt_input=normalized_input)
        account_provider_dispatch()
        return self.delegate.invoke_structured(
            prompt_ref=prompt_ref,
            prompt_input=normalized_input,
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
        normalized_input = _canonical_prompt_input(prompt_input)
        self._validate(prompt_ref=prompt_ref, prompt_input=normalized_input)
        delegate = self.delegate
        if not isinstance(delegate, _RuntimeToolCallingProvider):
            raise LLMInvocationError(
                LLMErrorCode.RUNTIME_MODE_BLOCKED,
                "selected provider does not support native tool calling",
            )
        account_provider_dispatch()
        return delegate.invoke_tool_call(
            prompt_ref=prompt_ref,
            prompt_input=normalized_input,
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


def _canonical_prompt_input(prompt_input: Mapping[str, object]) -> Mapping[str, object]:
    """Normalize the already-3-root Generic Repair envelope to FailureRecordV1.

    IMP-138's outer contract is unchanged. Historical Generic Schema Repair
    already emitted the exact nine FailureRecord field names but used two
    pre-v1.26 enum spellings (``RUNTIME`` and
    ``STRUCTURED_OUTPUT_VALIDATOR``). Only that exact legacy shape is
    normalized. The exact repair/revision envelope is assembly metadata: its
    base projection remains subject to the unchanged Product Prompt input
    contract, while FailureRecordV1 carries bounded allowed-change paths.
    """

    raw = prompt_input.get("failure_record")
    if not isinstance(raw, Mapping) or set(raw) != FAILURE_RECORD_FIELDS:
        return prompt_input
    if raw.get("failure_origin") != "RUNTIME" or raw.get("detected_by") != (
        "STRUCTURED_OUTPUT_VALIDATOR"
    ):
        return prompt_input
    failure_id = raw.get("failure_id")
    reason_code = raw.get("failure_reason_code")
    runtime_disposition = raw.get("runtime_disposition")
    experiment_disposition = raw.get("experiment_disposition")
    affected_paths = raw.get("affected_field_paths")
    evidence_refs = raw.get("evidence_refs")
    if not isinstance(failure_id, str) or not isinstance(reason_code, str):
        return prompt_input
    if runtime_disposition != "RETRYABLE" or experiment_disposition != "RUN_REPAIR":
        return prompt_input
    if not isinstance(affected_paths, list) or not isinstance(evidence_refs, list):
        return prompt_input
    canonical = build_failure_record_v1(
        failure_id=failure_id,
        failure_reason_code=reason_code,
        failure_origin="LLM_OUTPUT",
        detected_by="RUNTIME_SCHEMA_VALIDATOR",
        runtime_disposition="RETRYABLE",
        experiment_disposition="RUN_REPAIR",
        affected_field_paths=affected_paths,
        evidence_refs=evidence_refs,
    )
    return {**prompt_input, "failure_record": canonical}


__all__ = ["PromptInputGuardedProvider"]
