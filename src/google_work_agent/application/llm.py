"""Application services for LLM runtime routing and credential operations."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from google_work_agent.application.observability import (
    ObservabilityContext,
    Severity,
)
from google_work_agent.application.schema_validation import validate_output_schema
from google_work_agent.application.workflows.contracts import ABSOLUTE_MAX_LLM_CALLS
from google_work_agent.ports import (
    ActualRuntime,
    ApprovedModelInfo,
    AppSettings,
    AvailabilityState,
    CredentialStorageMode,
    HardwareCapability,
    HardwareCapabilityStatus,
    LLMCredentialStore,
    LLMErrorCode,
    LLMInvocationError,
    LLMRuntimeRouter,
    LLMRuntimeStatusReader,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    RequestedRuntimeMode,
    RouteDecision,
    RouteDecisionInput,
    RuntimePolicy,
    SchemaRepairer,
    StructuredLLMProvider,
    StructuredLLMResult,
    ToolCallingLLMProvider,
    ToolCallProviderResponse,
    ToolCallSchemaRepairer,
    ToolDefinition,
)


class LLMEventRecorder(Protocol):
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
        """Emit one sanitized LLM event."""


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
    status_service: LLMRuntimeStatusReader
    credential_service: LLMCredentialStore
    api_provider: StructuredLLMProvider
    ollama_provider_factory: Callable[[ApprovedModelInfo, AppSettings], StructuredLLMProvider]
    router: LLMRuntimeRouter
    runtime_policy: RuntimePolicy
    event_recorder: LLMEventRecorder = NullLLMEventRecorder()
    schema_repairer: SchemaRepairer | None = None
    tool_call_schema_repairer: ToolCallSchemaRepairer | None = None

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(1)
        self._llm_call_counts: dict[str, int] = {}
        self._llm_call_counts_lock = threading.Lock()

    def _consume_llm_call_budget(self, *, run_id: str | None) -> None:
        # The Run-level ABSOLUTE_MAX_LLM_CALLS ceiling from the Canonical
        # RunBudgetV1 contract (docs/06-agent-workflow.md), enforced here
        # because this is the one boundary every real Provider LLM call --
        # INITIAL, SCHEMA_REPAIR, SEMANTIC_REVISION, Planning revise, Review
        # recheck, Retrieval follow-up rounds -- passes through, regardless
        # of which Node/Agent issued it. Deliberately does not fail closed
        # when run_id is absent (e.g. test doubles / tooling invocations
        # with no Run context) -- production trace_context always carries
        # run_id.
        if run_id is None:
            return
        with self._llm_call_counts_lock:
            used = self._llm_call_counts.get(run_id, 0)
            if used + 1 > ABSOLUTE_MAX_LLM_CALLS:
                raise LLMInvocationError(
                    LLMErrorCode.LLM_CALL_BUDGET_EXHAUSTED,
                    f"run {run_id} exhausted its absolute LLM call budget "
                    f"({ABSOLUTE_MAX_LLM_CALLS} calls)",
                    retryable=False,
                )
            self._llm_call_counts[run_id] = used + 1

    def discard_run(self, *, run_id: str) -> None:
        with self._llm_call_counts_lock:
            self._llm_call_counts.pop(run_id, None)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None = None,
    ) -> StructuredLLMResult:
        self._consume_llm_call_budget(run_id=trace_context.run_id)
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
        self._consume_llm_call_budget(run_id=trace_context.run_id)
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
        settings = self.settings_service()
        requested_mode = RequestedRuntimeMode(settings.requested_runtime_mode)
        status = self.status_service.get_runtime_status(settings)
        api_provider_summary = cast(dict[str, object], status["api_provider"])
        ollama_summary = cast(dict[str, object], status["ollama"])
        approved_model = self.status_service.get_approved_model(settings.approved_model_id or "")
        hardware_capability = _hardware_from_dict(ollama_summary["hardware_capability"])
        decision = self.router.decide(
            RouteDecisionInput(
                build_profile=settings.deployment_profile,
                requested_mode=requested_mode,
                external_llm_consent=settings.external_llm_consent,
                api_credential_state=self.credential_service.describe_state(),
                api_probe=_probe_from_dict(api_provider_summary),
                hardware_capability=hardware_capability,
                ollama_probe=_probe_from_dict(ollama_summary),
                approved_model=approved_model,
            )
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
                "primary_runtime": decision.primary_runtime.value,
                "fallback_allowed": decision.fallback_allowed,
                "fallback_target": None
                if decision.fallback_target is None
                else decision.fallback_target.value,
                "safe_error_code": decision.safe_reason_code,
            },
            result_code="ROUTED",
            status="COMPLETED",
        )
        provider = self._resolve_provider(
            runtime=decision.primary_runtime,
            settings=settings,
            approved_model=approved_model,
            hardware_capability=hardware_capability,
        )
        try:
            return self._invoke_provider(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                requested_mode=requested_mode,
                trace_context=trace_context,
                fallback_reason=None,
                semantic_validate=semantic_validate,
            )
        except LLMInvocationError as error:
            if not self._should_fallback(
                error=error,
                decision=decision,
                requested_mode=requested_mode,
                settings=settings,
            ):
                raise
            self.event_recorder.record(
                event_name="LLM_FALLBACK_STARTED",
                severity=Severity.WARNING,
                correlation=trace_context,
                attributes={
                    "requested_mode": requested_mode.value,
                    "fallback_reason": error.code.value,
                    "from_runtime": decision.primary_runtime.value,
                    "to_runtime": (
                        decision.fallback_target.value
                        if decision.fallback_target is not None
                        else None
                    ),
                },
                result_code="FALLBACK_STARTED",
                status="STARTED",
            )
            api_provider = self._resolve_provider(
                runtime=ActualRuntime.API_LLM,
                settings=settings,
                approved_model=approved_model,
                hardware_capability=hardware_capability,
            )
            result = self._invoke_provider(
                provider=api_provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                requested_mode=requested_mode,
                trace_context=trace_context,
                fallback_reason=error.code.value,
                semantic_validate=semantic_validate,
            )
            self.event_recorder.record(
                event_name="LLM_FALLBACK_COMPLETED",
                severity=Severity.INFO,
                correlation=trace_context,
                attributes={
                    "requested_mode": requested_mode.value,
                    "fallback_reason": error.code.value,
                    "actual_runtime": result.actual_runtime.value,
                    "provider": result.provider,
                    "model": result.model,
                },
                result_code="FALLBACK_COMPLETED",
                status="COMPLETED",
            )
            return result

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
        provider = self._resolve_provider(
            runtime=ActualRuntime.LOCAL_GPU,
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

    def _resolve_provider(
        self,
        *,
        runtime: ActualRuntime,
        settings: AppSettings,
        approved_model: ApprovedModelInfo | None,
        hardware_capability: HardwareCapability,
    ) -> StructuredLLMProvider:
        if runtime is ActualRuntime.API_LLM:
            if not settings.external_llm_consent:
                raise LLMInvocationError(
                    LLMErrorCode.CONSENT_REQUIRED,
                    "external LLM consent is disabled",
                )
            if self.credential_service.read_secret() is None:
                raise LLMInvocationError(
                    LLMErrorCode.API_KEY_MISSING,
                    "LLM API key is not configured",
                )
            return self.api_provider
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

    def _invoke_provider(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        requested_mode: RequestedRuntimeMode,
        trace_context: ObservabilityContext,
        fallback_reason: str | None,
        semantic_validate: Callable[[object], object] | None = None,
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
        api_key = (
            self.credential_service.read_secret()
            if provider.runtime is ActualRuntime.API_LLM
            else None
        )
        try:
            payload = provider.invoke_structured(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                runtime_policy=self.runtime_policy,
                api_key=api_key,
            )
            structured_output, attempts = self._validate_or_repair(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                payload=payload.content,
                output_schema=output_schema,
                api_key=api_key,
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
            code = (
                LLMErrorCode.PROVIDER_TIMEOUT
                if provider.runtime is ActualRuntime.API_LLM
                else LLMErrorCode.PROVIDER_TIMEOUT
            )
            raise LLMInvocationError(code, "LLM invocation timed out", retryable=True) from error
        duration_ms = int((time.perf_counter() - started) * 1000)
        result = StructuredLLMResult(
            structured_output=structured_output,
            provider=provider.provider_name,
            model=payload.model,
            requested_mode=requested_mode,
            actual_runtime=provider.runtime,
            input_tokens=payload.input_tokens,
            output_tokens=payload.output_tokens,
            total_tokens=_sum_tokens(payload.input_tokens, payload.output_tokens),
            latency_ms=max(duration_ms, payload.latency_ms),
            estimated_cost_usd=payload.estimated_cost_usd,
            fallback_reason=fallback_reason,
            structured_output_attempts=attempts,
            provider_request_id=payload.provider_request_id,
            safe_error_code=None,
            provider_calls_consumed=1,
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

    def _validate_or_repair(
        self,
        *,
        provider: StructuredLLMProvider,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        payload: object,
        output_schema: OutputSchemaDefinition,
        api_key: str | None,
        trace_context: ObservabilityContext,
        semantic_validate: Callable[[object], object] | None,
    ) -> tuple[object, int]:
        candidate = _parse_payload(payload)
        validator_errors = self._collect_validation_errors(
            candidate, output_schema=output_schema, semantic_validate=semantic_validate
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
        if self.schema_repairer is None or self.runtime_policy.structured_output_repair_budget < 1:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "structured output did not satisfy schema",
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
        try:
            repaired = self.schema_repairer.repair(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                failed_output=candidate,
                output_schema=output_schema,
                runtime_policy=self.runtime_policy,
                api_key=api_key,
                attempt_no=1,
                max_attempts=self.runtime_policy.structured_output_repair_budget,
                failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
                validator_errors=tuple(validator_errors),
            )
        except LLMInvocationError:
            raise
        repaired_errors = self._collect_validation_errors(
            repaired, output_schema=output_schema, semantic_validate=semantic_validate
        )
        if repaired_errors:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "schema repair did not produce a valid payload",
            )
        return repaired, 2

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
            provider_calls_consumed=1,
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
        shape_errors = validate_output_schema(candidate, output_schema.json_schema)
        if shape_errors or semantic_validate is None:
            return shape_errors
        try:
            semantic_validate(candidate)
        except ValueError as error:
            return [str(error)]
        return []

    def _should_fallback(
        self,
        *,
        error: LLMInvocationError,
        decision: RouteDecision,
        requested_mode: RequestedRuntimeMode,
        settings: AppSettings,
    ) -> bool:
        if requested_mode is not RequestedRuntimeMode.AUTO:
            return False
        if not settings.external_llm_consent:
            return False
        if not decision.fallback_allowed:
            return False
        return error.code in {
            LLMErrorCode.LOCAL_UNAVAILABLE,
            LLMErrorCode.MODEL_NOT_FOUND,
            LLMErrorCode.MODEL_NOT_APPROVED,
            LLMErrorCode.MODEL_LOAD_FAILED,
            LLMErrorCode.GPU_OOM,
            LLMErrorCode.PROVIDER_TIMEOUT,
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
        }


_JSON_PATH_PREFIX = re.compile(r"^\$[\w.\[\]]*")


def _leading_json_path(message: str) -> str | None:
    match = _JSON_PATH_PREFIX.match(message)
    if match is None or match.group(0) == "$":
        return None
    return match.group(0)


@dataclass(frozen=True, slots=True)
class PromptRepairSchemaRepairer:
    """Real Schema Repair boundary.

    Re-invokes the same routed ``provider`` with the failed prompt's sibling
    ``<prompt_id>.repair`` slot (``prompt_id`` with ``.repair`` appended,
    e.g. ``work_analysis.analyze`` -> ``work_analysis.analyze.repair``) for
    one bounded attempt, using the exact ``repair_input`` shape already
    proven by
    ``experiments/runner/r84_gate_runner.py::_run_repair_case`` against the
    matching ``*-repair-input.schema.json`` contracts (see e.g.
    ``experiments/datasets/google_workspace/schemas/work-analysis-repair-input.schema.json``).

    By default (``prompt_loader=None``) this uses ``load_prompt_reference``,
    which enforces ``RUNTIME_ACTIVE``: while a subgraph's ``.repair`` slot is
    still ``DRAFT`` (prompts/agent/README.md's Node DEV -> Node HOLDOUT ->
    G01 Safety Gate has not promoted it yet), this raises the same
    ``LLMInvocationError`` a caller with no repairer configured at all would
    raise, instead of using an unapproved prompt in production. Repair
    activates automatically, with no further code change, the moment a
    subgraph's ``.repair`` slot is promoted to ``RUNTIME_ACTIVE``.

    ``prompt_loader`` is an explicit DEV-only escape hatch: passing
    ``load_prompt_reference_for_evaluation`` (the same official,
    already-approved evaluation loader ``r84_gate_runner.py`` uses to read
    DRAFT slots for Gate scoring) lets an offline Contract DEV Runner
    actually exercise a DRAFT ``.repair`` prompt's real content, without
    touching any prompt's ``activation_status`` in the manifest. Production
    callers must never set this -- leaving it ``None`` is what preserves the
    fail-closed guarantee above.
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
        from google_work_agent.application.workflows.prompt_registry import (
            InactivePromptArtifactError,
            default_prompt_manifest_path,
            load_prompt_reference,
        )

        manifest_path = self.manifest_path or default_prompt_manifest_path()
        loader = self.prompt_loader or load_prompt_reference
        # The sibling repair slot's id is the failed prompt's own prompt_id
        # with ".repair" appended -- e.g. "work_analysis.analyze" ->
        # "work_analysis.analyze.repair". Each node owns its own repair slot
        # in prompt-manifest-v0.9.0.json (unlike v0.8.3.json's one
        # generic "<namespace>.repair" slot per agent role).
        repair_prompt_id = f"{prompt_ref.prompt_id}.repair"
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
    """Shared repair-input shape for both the free-JSON and tool-calling repair boundaries."""

    affected_field_paths = sorted(
        {path for message in validator_errors if (path := _leading_json_path(message)) is not None}
    )
    return {
        "schema_version": 1,
        "original_input": dict(prompt_input),
        "previous_output": failed_output,
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
        "validator_errors": list(validator_errors),
        "changed_fields_allowed": affected_field_paths,
        "attempt_no": attempt_no,
        "max_attempts": max_attempts,
    }


@dataclass(frozen=True, slots=True)
class PromptRepairToolCallRepairer:
    """Real Schema Repair boundary for the native tool-calling invocation path.

    Structurally parallel to ``PromptRepairSchemaRepairer`` (same sibling
    ``<prompt_id>.repair`` slot lookup, same DRAFT fail-closed default, same
    DEV-only ``prompt_loader`` escape hatch), except the repair call stays in
    tool-calling mode: it re-invokes ``provider.invoke_tool_call`` with the
    same ``tools`` list, then applies ``mapper`` to the repaired tool call
    before returning -- so the result is already the Node's Typed-Result
    candidate, exactly like ``PromptRepairSchemaRepairer.repair`` returns an
    already-parsed candidate.
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
        from google_work_agent.application.workflows.prompt_registry import (
            InactivePromptArtifactError,
            default_prompt_manifest_path,
            load_prompt_reference,
        )

        manifest_path = self.manifest_path or default_prompt_manifest_path()
        loader = self.prompt_loader or load_prompt_reference
        repair_prompt_id = f"{prompt_ref.prompt_id}.repair"
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
class GetLLMConnectionService:
    runtime_status_service: LLMRuntimeStatusReader
    settings_service: Callable[[], AppSettings]

    def __call__(self) -> dict[str, object]:
        return self.runtime_status_service.get_runtime_status(self.settings_service())


@dataclass(frozen=True, slots=True)
class StoreLLMApiKeyService:
    credential_service: LLMCredentialStore

    def __call__(self, *, api_key: str, storage_mode: CredentialStorageMode) -> dict[str, str]:
        state = self.credential_service.store(api_key=api_key, mode=storage_mode)
        return {"credential_state": state.value}


@dataclass(frozen=True, slots=True)
class DeleteLLMApiKeyService:
    credential_service: LLMCredentialStore

    def __call__(self) -> dict[str, str]:
        state = self.credential_service.delete()
        return {"credential_state": state.value}


@dataclass(frozen=True, slots=True)
class TestLLMConnectionService:
    runtime_service: LLMRuntimeService

    def __call__(self) -> dict[str, object]:
        return self.runtime_service.test_connection()


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
    from google_work_agent.ports import HardwareCapabilityStatus

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
