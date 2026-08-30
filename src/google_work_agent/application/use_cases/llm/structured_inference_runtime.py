"""LLM-owner-local structured-inference application support."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
    ProjectExternalLlmTransferScopeQueryV1,
)
from google_work_agent.ports.llm import (
    ActualRuntime,
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    LLMErrorCode,
    LLMInvocationError,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    RequestedRuntimeMode,
    RuntimePolicy,
    SchemaRepairer,
    StructuredLLMProvider,
    StructuredLLMResult,
    ToolCallingLLMProvider,
    ToolCallProviderResponse,
    ToolCallSchemaRepairer,
    ToolDefinition,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.observability import (
    LLMEventRecorder,
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports.system.contracts.runtime import AppSettings


class StructuredLLMRuntime(Protocol):
    """Minimal structured-generation capability required by workflow agents."""

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        """Generate and validate one structured workflow result.

        ``output_schema`` only enforces JSON-schema shape. ``semantic_validate``
        is an optional deeper contract check (e.g. work_analysis's finding
        cross-references) that runs after shape validation passes; a raised
        ``ValueError`` from it is treated exactly like a shape failure and
        shares the same one-attempt repair budget, instead of escaping
        uncaught into the caller.
        """

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        """Generate one native tool-calling turn and validate its mapped result.

        ``mapper`` deterministically converts the provider's chosen tool
        call(s) into the Node's Typed-Result-shaped candidate (or raises
        ``ValueError`` for 0 calls, 2+ calls, an unknown function, or
        malformed arguments -- treated exactly like a shape failure).
        ``output_schema``/``semantic_validate`` then validate the MAPPED
        candidate, sharing the same one-attempt repair budget as
        ``invoke_structured``, except repair also stays in tool-calling mode.
        """

    def discard_run(self, *, run_id: str) -> None:
        """Release any per-run LLM call accounting held for ``run_id``."""


class _RuntimeStatusAccess(Protocol):
    def get_runtime_status(self, settings: AppSettings) -> dict[str, object]: ...

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None: ...


@dataclass(frozen=True, slots=True)
class NullLLMEventRecorder:
    def record(
        self,
        *,
        event_name: str,
        severity: Severity,
        correlation: ObservabilityContext,
        attributes: Mapping[str, object],
        result_code: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        del event_name, severity, correlation, attributes, result_code, status, duration_ms


@dataclass
class LLMRuntimeService:
    settings_service: Callable[[], AppSettings]
    status_service: _RuntimeStatusAccess
    ollama_provider_factory: Callable[[ApprovedModelInfo, AppSettings], StructuredLLMProvider]
    runtime_policy: RuntimePolicy
    structured_inference: StructuredInferencePort
    event_recorder: LLMEventRecorder = NullLLMEventRecorder()
    schema_repairer: SchemaRepairer | None = None
    tool_call_schema_repairer: ToolCallSchemaRepairer | None = None
    project_external_scope: ProjectExternalLlmTransferScopeHandler | None = None
    now_ms: Callable[[], int] = lambda: int(time.time() * 1000)

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(1)

    def discard_run(self, *, run_id: str) -> None:
        # No-op: the authoritative, checkpoint-persistent Run-level LLM call
        # budget lives in RunBudgetV1 (state["retry_budget"]), gated by each
        # native subgraph node via agent_kernel.ensure_llm_call_budget /
        # consume_llm_call_budget before/after its real Provider call. This
        # service used to keep its own in-memory per-run counter here (reset
        # on Run finalize via this method); that counter was a second,
        # non-checkpoint-safe source of truth for the same ABSOLUTE_MAX_LLM_CALLS
        # ceiling and has been removed. The method stays to satisfy the
        # StructuredLLMRuntime Protocol and its existing runtime.py caller.
        del run_id

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        if not self._semaphore.acquire(
            timeout=max(
                self.runtime_policy.local_timeout_seconds,
                self.runtime_policy.api_timeout_seconds,
            )
        ):
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT,
                "LLM concurrency permit was not acquired in time",
                retryable=True,
            )
        try:
            return self._invoke_locked(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                trace_context=trace_context,
                semantic_validate=semantic_validate,
            )
        finally:
            self._semaphore.release()

    def invoke_tool_call(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        if not self._semaphore.acquire(
            timeout=max(
                self.runtime_policy.local_timeout_seconds,
                self.runtime_policy.api_timeout_seconds,
            )
        ):
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT,
                "LLM concurrency permit was not acquired in time",
                retryable=True,
            )
        try:
            return self._invoke_tool_call_locked(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                tools=tools,
                mapper=mapper,
                output_schema=output_schema,
                trace_context=trace_context,
                semantic_validate=semantic_validate,
            )
        finally:
            self._semaphore.release()

    def test_connection(self) -> dict[str, object]:
        settings = self.settings_service()
        status = self.status_service.get_runtime_status(settings)
        requested_mode = RequestedRuntimeMode(settings.requested_runtime_mode)
        if requested_mode is RequestedRuntimeMode.API_LLM and not settings.external_llm_consent:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM consent is disabled",
            )
        return status

    def _invoke_locked(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
    ) -> StructuredLLMResult:
        requested_mode = RequestedRuntimeMode(self.settings_service().requested_runtime_mode)
        external_scope = self._publish_external_scope(
            requested_mode=requested_mode,
            prompt_input=prompt_input,
            trace_context=trace_context,
        )
        result = self.structured_inference.infer(
            requested_mode.value,
            prompt_ref,
            prompt_input,
            output_schema,
            external_scope,
        )
        if semantic_validate is not None:
            semantic_validate(result.structured_output)
        return StructuredLLMResult(
            structured_output=result.structured_output,
            provider=result.provider,
            model=result.model,
            requested_mode=requested_mode,
            actual_runtime=ActualRuntime(result.actual_runtime),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.input_tokens + result.output_tokens,
            latency_ms=result.latency_ms,
            estimated_cost_usd=None,
            fallback_reason=result.fallback_reason,
            structured_output_attempts=1,
            provider_request_id=None,
            safe_error_code=None,
        )

    def _publish_external_scope(
        self,
        *,
        requested_mode: RequestedRuntimeMode,
        prompt_input: Mapping[str, object],
        trace_context: ObservabilityContext,
    ) -> ExternalLlmTransferScopeV1 | None:
        if requested_mode is RequestedRuntimeMode.LOCAL_GPU:
            return None
        if trace_context.run_id is None or self.project_external_scope is None:
            return None
        source_kinds = tuple(sorted(str(key) for key in prompt_input)) or ("PROMPT_INPUT",)
        data_classes = _external_data_classes(source_kinds)
        return self.project_external_scope(
            ProjectExternalLlmTransferScopeQueryV1(
                schema_version=1,
                run_id=trace_context.run_id,
                source_kinds=source_kinds,
                data_classes=data_classes,
                occurred_at_ms=self.now_ms(),
            )
        )

    def _invoke_tool_call_locked(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
    ) -> StructuredLLMResult:
        """Routes and dispatches one tool-calling turn.

        Reuses the same hardware-gate/consent routing decision as
        ``_invoke_locked``, but never falls back to ``API_LLM``: no adapter
        in this codebase implements ``ToolCallingLLMProvider`` for the API
        path yet, so a fallback attempt would just fail differently. Native
        tool-calling is LOCAL_GPU-only until that changes.
        """
        settings = self.settings_service()
        requested_mode = RequestedRuntimeMode(settings.requested_runtime_mode)
        status = self.status_service.get_runtime_status(settings)
        ollama_summary = cast(dict[str, object], status["ollama"])
        approved_model = self.status_service.get_approved_model(settings.approved_model_id or "")
        hardware_capability = _hardware_from_dict(ollama_summary["hardware_capability"])
        provider = self._resolve_local_tool_provider(
            settings=settings,
            approved_model=approved_model,
            hardware_capability=hardware_capability,
        )
        self.event_recorder.record(
            event_name="LLM_RUNTIME_SELECTED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "primary_runtime": ActualRuntime.LOCAL_GPU.value,
                "fallback_allowed": False,
                "fallback_target": None,
                "safe_error_code": None,
            },
            result_code="ROUTED",
            status="COMPLETED",
        )
        return self._invoke_tool_call_provider(
            provider=cast(ToolCallingLLMProvider, provider),
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            tools=tools,
            mapper=mapper,
            output_schema=output_schema,
            requested_mode=requested_mode,
            trace_context=trace_context,
            semantic_validate=semantic_validate,
        )

    def _resolve_local_tool_provider(
        self,
        *,
        settings: AppSettings,
        approved_model: ApprovedModelInfo | None,
        hardware_capability: HardwareCapability,
    ) -> StructuredLLMProvider:
        if hardware_capability.capability_status is not HardwareCapabilityStatus.VALIDATED:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                "local hardware capability is not validated for LOCAL_GPU",
            )
        if approved_model is None:
            raise LLMInvocationError(
                LLMErrorCode.MODEL_NOT_APPROVED,
                "approved model is unavailable",
            )
        if settings.ollama_endpoint is None:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                "Ollama endpoint is not configured",
            )
        return self.ollama_provider_factory(approved_model, settings)

    def _invoke_tool_call_provider(
        self,
        *,
        provider: ToolCallingLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        output_schema: OutputSchemaDefinition,
        requested_mode: RequestedRuntimeMode,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
    ) -> StructuredLLMResult:
        started = time.perf_counter()
        self.event_recorder.record(
            event_name="LLM_CALL_STARTED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "actual_runtime": provider.runtime.value,
                "provider": provider.provider_name,
            },
            result_code="STARTED",
            status="STARTED",
        )
        try:
            response = provider.invoke_tool_call(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                tools=tools,
                runtime_policy=self.runtime_policy,
                api_key=None,
            )
            structured_output, attempts = self._validate_or_repair_tool_call(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                tools=tools,
                mapper=mapper,
                response=response,
                output_schema=output_schema,
                trace_context=trace_context,
                semantic_validate=semantic_validate,
            )
        except ValueError as error:
            raise LLMInvocationError(
                LLMErrorCode.INVALID_PROVIDER_RESPONSE,
                str(error),
            ) from error
        except LLMInvocationError:
            raise
        except TimeoutError as error:
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT, "LLM invocation timed out", retryable=True
            ) from error
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = StructuredLLMResult(
            structured_output=structured_output,
            provider=provider.provider_name,
            model=response.model,
            requested_mode=requested_mode,
            actual_runtime=provider.runtime,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            total_tokens=_sum_tokens(response.input_tokens, response.output_tokens),
            latency_ms=max(duration_ms, response.latency_ms),
            estimated_cost_usd=response.estimated_cost_usd,
            fallback_reason=None,
            structured_output_attempts=attempts,
            provider_request_id=response.provider_request_id,
            safe_error_code=None,
            provider_calls_consumed=attempts,
        )
        self.event_recorder.record(
            event_name="LLM_CALL_COMPLETED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "requested_mode": requested_mode.value,
                "actual_runtime": result.actual_runtime.value,
                "provider": result.provider,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "total_tokens": result.total_tokens,
                "estimated_cost_usd": result.estimated_cost_usd,
                "fallback_reason": result.fallback_reason,
                "structured_output_attempts": result.structured_output_attempts,
            },
            result_code="COMPLETED",
            status="COMPLETED",
            duration_ms=result.latency_ms,
        )
        return result

    def _validate_or_repair_tool_call(
        self,
        *,
        provider: ToolCallingLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        response: ToolCallProviderResponse,
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
    ) -> tuple[object, int]:
        candidate, validator_errors = self._map_and_validate_tool_call(
            response,
            mapper=mapper,
            output_schema=output_schema,
            semantic_validate=semantic_validate,
        )
        if not validator_errors:
            return candidate, 1
        self.event_recorder.record(
            event_name="LLM_SCHEMA_VALIDATION_FAILED",
            severity=Severity.WARNING,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "failure_count": len(validator_errors),
                "failure_reason_code": LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            },
            result_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            status="FAILED",
        )
        if (
            self.tool_call_schema_repairer is None
            or self.runtime_policy.structured_output_repair_budget < 1
        ):
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "tool call output did not satisfy schema",
            )
        self.event_recorder.record(
            event_name="LLM_REPAIR_REQUESTED",
            severity=Severity.INFO,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "attempt_no": 1,
                "repair_kind": "SCHEMA_REPAIR",
                "failure_reason_code": LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            },
            result_code="REPAIR_REQUESTED",
            status="STARTED",
        )
        repaired = self.tool_call_schema_repairer.repair(
            provider=provider,
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            tools=tools,
            mapper=mapper,
            failed_output=candidate,
            output_schema=output_schema,
            runtime_policy=self.runtime_policy,
            api_key=None,
            attempt_no=1,
            max_attempts=self.runtime_policy.structured_output_repair_budget,
            failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
            validator_errors=tuple(validator_errors),
        )
        repaired_errors = self._collect_validation_errors(
            repaired, output_schema=output_schema, semantic_validate=semantic_validate
        )
        if repaired_errors:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "schema repair did not produce a valid payload",
            )
        return repaired, 2

    @staticmethod
    def _map_and_validate_tool_call(
        response: ToolCallProviderResponse,
        *,
        mapper: Callable[[ToolCallProviderResponse], object],
        output_schema: OutputSchemaDefinition,
        semantic_validate: Callable[[object], object] | None,
    ) -> tuple[object, list[str]]:
        """Applies ``mapper`` first: a mapping failure (0/2+ calls, unknown
        function, malformed arguments) is treated exactly like a shape
        failure, sharing the same repair budget.
        """
        try:
            candidate = mapper(response)
        except ValueError as error:
            debug_calls = [
                {"name": call.name, "arguments": dict(call.arguments)} for call in response.calls
            ]
            return {"tool_calls": debug_calls}, [str(error)]
        return candidate, LLMRuntimeService._collect_validation_errors(
            candidate, output_schema=output_schema, semantic_validate=semantic_validate
        )

    @staticmethod
    def _collect_validation_errors(
        candidate: object,
        *,
        output_schema: OutputSchemaDefinition,
        semantic_validate: Callable[[object], object] | None,
    ) -> list[str]:
        """Shape errors first: a semantically-invalid candidate that is also
        shape-invalid should be reported/repaired for its shape violations,
        not a confusing mix of both validators' output.
        """
        shape_errors = cast(list[str], validate_output_schema(candidate, output_schema.json_schema))
        if shape_errors or semantic_validate is None:
            return shape_errors
        try:
            semantic_validate(candidate)
        except ValueError as error:
            return [str(error)]
        return []


_JSON_PATH_PREFIX = re.compile(r"^\$[\w.\[\]]*")
_SEMANTIC_VARIANT_SUFFIXES = (".revise", ".recheck")


def _leading_json_path(message: str) -> str | None:
    match = _JSON_PATH_PREFIX.match(message)
    if match is None or match.group(0) == "$":
        return None
    return match.group(0)


def _repair_prompt_id(prompt_id: str) -> str:
    """Return the registered SCHEMA_REPAIR slot for one semantic node variant."""

    for suffix in _SEMANTIC_VARIANT_SUFFIXES:
        if prompt_id.endswith(suffix):
            return f"{prompt_id[: -len(suffix)]}.repair"
    return f"{prompt_id}.repair"


@dataclass(frozen=True, slots=True)
class PromptRepairSchemaRepairer:
    """Real Schema Repair boundary.

    Re-invokes the same routed ``provider`` with the failed semantic node's
    registered SCHEMA_REPAIR sibling. Initial prompts resolve to
    ``<prompt_id>.repair``; ``.revise``/``.recheck`` prompts normalize back to
    the owning node's ``<node>.repair`` slot. This preserves the 27-slot
    Runtime Prompt contract without inventing ``.revise.repair`` or
    ``.recheck.repair`` PromptRefs.
    """

    manifest_path: Path | None = None
    prompt_loader: Callable[[str, Path], PromptReference] | None = None

    def repair(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
        attempt_no: int,
        max_attempts: int,
        failure_reason_code: str,
        validator_errors: tuple[str, ...],
    ) -> object:
        from google_work_agent.application.prompt_runtime.prompt_registry import (
            InactivePromptArtifactError,
            default_prompt_manifest_path,
            load_prompt_reference,
        )

        manifest_path = self.manifest_path or default_prompt_manifest_path()
        loader = self.prompt_loader or load_prompt_reference
        repair_prompt_id = _repair_prompt_id(prompt_ref.prompt_id)
        try:
            repair_prompt_ref = loader(repair_prompt_id, manifest_path)
        except (LookupError, InactivePromptArtifactError) as error:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                f"{repair_prompt_id} repair prompt is unavailable: {error}",
            ) from error

        repair_input = _build_repair_input(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            failed_output=failed_output,
            attempt_no=attempt_no,
            max_attempts=max_attempts,
            failure_reason_code=failure_reason_code,
            validator_errors=validator_errors,
        )
        payload = provider.invoke_structured(
            prompt_ref=repair_prompt_ref,
            prompt_input=repair_input,
            output_schema=output_schema,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )
        return _parse_payload(payload.content)


def _build_repair_input(
    *,
    prompt_ref: PromptReference,
    prompt_input: Mapping[str, object],
    failed_output: object,
    attempt_no: int,
    max_attempts: int,
    failure_reason_code: str,
    validator_errors: tuple[str, ...],
) -> dict[str, object]:
    """Shared repair-input shape for both the free-JSON and tool-calling repair boundaries.

    Root shape is exactly base_projection + candidate_output + failure_record
    (15 section 9.2 / prompt-runtime-input-contract-v1.json's repair/revise
    slots' allowed_root_fields) -- no legacy original_input/previous_output/
    validator_errors/changed_fields_allowed/attempt_no root fields. attempt_no
    and max_attempts stay function parameters only (attempt_no folds into
    failure_id below; max_attempts is Runtime/Trace-only and Schema Repair is
    bounded to one attempt anyway, so the model never needs it). The raw
    validator_errors message text is normalized away -- affected_field_paths
    already carries the actionable signal, matching failure_record's fixed
    schema (15 section 5).
    """

    del max_attempts
    affected_field_paths = sorted(
        {path for message in validator_errors if (path := _leading_json_path(message)) is not None}
    )
    return {
        "base_projection": dict(prompt_input),
        "candidate_output": failed_output,
        "failure_record": {
            "schema_version": 1,
            "failure_id": f"{prompt_ref.prompt_id}:{attempt_no}",
            "failure_reason_code": failure_reason_code,
            "failure_origin": "RUNTIME",
            "detected_by": "STRUCTURED_OUTPUT_VALIDATOR",
            "runtime_disposition": "RETRYABLE",
            "experiment_disposition": "RUN_REPAIR",
            "affected_field_paths": affected_field_paths,
            "evidence_refs": [],
        },
    }


@dataclass(frozen=True, slots=True)
class PromptRepairToolCallRepairer:
    """Real Schema Repair boundary for the native tool-calling invocation path.

    Structurally parallel to ``PromptRepairSchemaRepairer`` and uses the same
    semantic-variant normalization to the owning node's registered ``.repair``
    slot. The repair call stays in tool-calling mode and is mapped back to the
    node's Typed Result before validation resumes.
    """

    manifest_path: Path | None = None
    prompt_loader: Callable[[str, Path], PromptReference] | None = None

    def repair(
        self,
        *,
        provider: ToolCallingLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        tools: Sequence[ToolDefinition],
        mapper: Callable[[ToolCallProviderResponse], object],
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        runtime_policy: RuntimePolicy,
        api_key: str | None,
        attempt_no: int,
        max_attempts: int,
        failure_reason_code: str,
        validator_errors: tuple[str, ...],
    ) -> object:
        del output_schema  # shape re-check happens in _validate_or_repair_tool_call after mapping
        from google_work_agent.application.prompt_runtime.prompt_registry import (
            InactivePromptArtifactError,
            default_prompt_manifest_path,
            load_prompt_reference,
        )

        manifest_path = self.manifest_path or default_prompt_manifest_path()
        loader = self.prompt_loader or load_prompt_reference
        repair_prompt_id = _repair_prompt_id(prompt_ref.prompt_id)
        try:
            repair_prompt_ref = loader(repair_prompt_id, manifest_path)
        except (LookupError, InactivePromptArtifactError) as error:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                f"{repair_prompt_id} repair prompt is unavailable: {error}",
            ) from error

        repair_input = _build_repair_input(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            failed_output=failed_output,
            attempt_no=attempt_no,
            max_attempts=max_attempts,
            failure_reason_code=failure_reason_code,
            validator_errors=validator_errors,
        )
        response = provider.invoke_tool_call(
            prompt_ref=repair_prompt_ref,
            prompt_input=repair_input,
            tools=tools,
            runtime_policy=runtime_policy,
            api_key=api_key,
        )
        return mapper(response)


@dataclass(frozen=True, slots=True)
class TestLLMConnectionService:
    runtime_service: LLMRuntimeService

    def __call__(self) -> dict[str, object]:
        return self.runtime_service.test_connection()


def _external_data_classes(
    source_kinds: tuple[str, ...],
) -> tuple[
    Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"],
    ...,
]:
    """Classify only bounded source names; raw prompt values never enter disclosure."""

    lowered = tuple(item.lower() for item in source_kinds)
    classes: set[
        Literal["USER_REQUEST", "RESOURCE_METADATA", "EVIDENCE_EXCERPT", "PLAN_CONTEXT"]
    ] = set()
    if any(any(marker in item for marker in ("user", "request", "query")) for item in lowered):
        classes.add("USER_REQUEST")
    if any(
        any(marker in item for marker in ("resource", "calendar", "gmail", "task", "tool"))
        for item in lowered
    ):
        classes.add("RESOURCE_METADATA")
    if any(any(marker in item for marker in ("evidence", "excerpt", "source")) for item in lowered):
        classes.add("EVIDENCE_EXCERPT")
    if (
        any(
            any(marker in item for marker in ("plan", "context", "analysis", "route", "goal"))
            for item in lowered
        )
        or not classes
    ):
        classes.add("PLAN_CONTEXT")
    return tuple(sorted(classes))


def _parse_payload(payload: object) -> object:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _sum_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def _probe_from_dict(value: object) -> ProbeResult:
    if not isinstance(value, dict):
        return ProbeResult(availability=AvailabilityState.UNKNOWN)
    availability = value.get("availability", AvailabilityState.UNKNOWN.value)
    return ProbeResult(
        availability=AvailabilityState(str(availability)),
        safe_error_code=(
            None if value.get("safe_error_code") is None else str(value.get("safe_error_code"))
        ),
        last_probe_at_ms=_optional_int(value.get("last_probe")),
        metadata={
            key: item
            for key, item in value.items()
            if key not in {"availability", "safe_error_code", "last_probe"}
        },
    )


def _hardware_from_dict(value: object) -> HardwareCapability:
    if not isinstance(value, dict):
        raise ValueError("hardware capability must be an object")
    return HardwareCapability(
        cpu_arch=str(value.get("cpu_arch", "unknown")),
        core_summary=str(value.get("core_summary", "unknown")),
        memory_bytes=_optional_int(value.get("memory_bytes")),
        gpu_present=bool(value.get("gpu_present", False)),
        gpu_vendor=None if value.get("gpu_vendor") is None else str(value.get("gpu_vendor")),
        gpu_name=None if value.get("gpu_name") is None else str(value.get("gpu_name")),
        gpu_memory_bytes=_optional_int(value.get("gpu_memory_bytes")),
        capability_status=HardwareCapabilityStatus(str(value.get("capability_status", "UNKNOWN"))),
        safe_reason_codes=tuple(str(item) for item in value.get("safe_reason_codes", ())),
    )


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
