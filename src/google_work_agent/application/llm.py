"""Application services for LLM runtime routing and credential operations."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from google_work_agent.adapters.llm import (
    CredentialStorageMode,
    DeterministicLLMRuntimeRouter,
    LLMCredentialService,
    LLMRuntimeStatusService,
    validate_output_schema,
)
from google_work_agent.adapters.runtime import AppSettings
from google_work_agent.application.observability import (
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports import (
    ActualRuntime,
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    LLMErrorCode,
    LLMInvocationError,
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
    ) -> StructuredLLMResult:
        """Generate and validate one structured workflow result."""


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
    status_service: LLMRuntimeStatusService
    credential_service: LLMCredentialService
    api_provider: StructuredLLMProvider
    ollama_provider_factory: Callable[[ApprovedModelInfo, AppSettings], StructuredLLMProvider]
    router: DeterministicLLMRuntimeRouter
    runtime_policy: RuntimePolicy
    event_recorder: LLMEventRecorder = NullLLMEventRecorder()
    schema_repairer: SchemaRepairer | None = None

    def __post_init__(self) -> None:
        self._semaphore = threading.Semaphore(1)

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
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
    ) -> StructuredLLMResult:
        settings = self.settings_service()
        requested_mode = RequestedRuntimeMode(settings.requested_runtime_mode)
        status = self.status_service.get_runtime_status(settings)
        api_provider_summary = cast(dict[str, object], status["api_provider"])
        ollama_summary = cast(dict[str, object], status["ollama"])
        approved_model = self.status_service.approved_models.get(settings.approved_model_id or "")
        decision = self.router.decide(
            RouteDecisionInput(
                build_profile=settings.deployment_profile,
                requested_mode=requested_mode,
                external_llm_consent=settings.external_llm_consent,
                api_credential_state=self.credential_service.describe_state(),
                api_probe=_probe_from_dict(api_provider_summary),
                hardware_capability=_hardware_from_dict(ollama_summary["hardware_capability"]),
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
            )
            result = self._invoke_provider(
                provider=api_provider,
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                requested_mode=requested_mode,
                trace_context=trace_context,
                fallback_reason=error.code.value,
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

    def _resolve_provider(
        self,
        *,
        runtime: ActualRuntime,
        settings: AppSettings,
        approved_model: ApprovedModelInfo | None,
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
                prompt_ref=prompt_ref,
                payload=payload.content,
                output_schema=output_schema,
                trace_context=trace_context,
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
        prompt_ref: PromptReference,
        payload: object,
        output_schema: OutputSchemaDefinition,
        trace_context: ObservabilityContext,
    ) -> tuple[object, int]:
        candidate = _parse_payload(payload)
        errors = validate_output_schema(candidate, output_schema.json_schema)
        if not errors:
            return candidate, 1
        self.event_recorder.record(
            event_name="LLM_SCHEMA_VALIDATION_FAILED",
            severity=Severity.WARNING,
            correlation=trace_context,
            attributes={
                "prompt_id": prompt_ref.prompt_id,
                "prompt_version": prompt_ref.prompt_version,
                "prompt_content_hash": prompt_ref.content_hash,
                "failure_count": len(errors),
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
        repaired = self.schema_repairer.repair(
            prompt_ref=prompt_ref,
            failed_output=candidate,
            output_schema=output_schema,
            attempt_no=1,
            failure_reason_code=LLMErrorCode.OUTPUT_SCHEMA_INVALID.value,
        )
        repaired_errors = validate_output_schema(repaired, output_schema.json_schema)
        if repaired_errors:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
                "schema repair did not produce a valid payload",
            )
        return repaired, 2

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


@dataclass(frozen=True, slots=True)
class GetLLMConnectionService:
    runtime_status_service: LLMRuntimeStatusService
    settings_service: Callable[[], AppSettings]

    def __call__(self) -> dict[str, object]:
        return self.runtime_status_service.get_runtime_status(self.settings_service())


@dataclass(frozen=True, slots=True)
class StoreLLMApiKeyService:
    credential_service: LLMCredentialService

    def __call__(self, *, api_key: str, storage_mode: CredentialStorageMode) -> dict[str, str]:
        state = self.credential_service.store(api_key=api_key, mode=storage_mode)
        return {"credential_state": state.value}


@dataclass(frozen=True, slots=True)
class DeleteLLMApiKeyService:
    credential_service: LLMCredentialService

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
