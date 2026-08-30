"""The sole production API/local structured-inference runtime binding."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.ports.llm import (
    ActualRuntime,
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    LLMCredentialState,
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
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema
from google_work_agent.ports.llm.structured_inference_port import StructuredInferenceResultV1
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.observability import (
    LLMEventRecorder,
    ObservabilityContext,
    Severity,
)
from google_work_agent.ports.system.contracts.runtime import AppSettings
from google_work_agent.ports.system.hardware_probe_port import HardwareProbePort


@dataclass(frozen=True, slots=True)
class NullLLMEventRecorder:
    def record(self, **kwargs: object) -> None:
        del kwargs


@dataclass
class StructuredInferenceRuntimeRouter:
    """Select API/Ollama leaves and perform the single permitted AUTO fallback."""

    settings_service: Callable[[], AppSettings]
    status_service: LlmRuntimeStatusRouter
    credential_service: LlmCredentialRouter
    hardware_probe: HardwareProbePort
    api_provider_name: str
    api_provider: StructuredLLMProvider
    ollama_provider_factory: Callable[[ApprovedModelInfo, AppSettings], StructuredLLMProvider]
    runtime_policy: RuntimePolicy
    event_recorder: LLMEventRecorder = NullLLMEventRecorder()
    schema_repairer: SchemaRepairer | None = None
    prompt_manifest_path: Path | None = None
    checkpoint: CheckpointPort | None = None

    def __post_init__(self) -> None:
        self._api_leaf: StructuredLLMProvider = self.api_provider

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        """Expose the router-owned approved-model lookup to tool-call orchestration."""

        return self.status_service.get_approved_model(model_id)

    def get_runtime_status(self, settings: AppSettings) -> dict[str, object]:
        """Project the router's canonical local-runtime facts for tool calls."""

        hardware = self.hardware_probe.probe()
        capability_status = (
            HardwareCapabilityStatus.VALIDATED
            if hardware.local_runtime_eligible
            else HardwareCapabilityStatus.NOT_VALIDATED
        )
        return {
            "ollama": {
                "availability": self.status_service.get_status("ollama").availability,
                "hardware_capability": {
                    "cpu_arch": "unknown",
                    "core_summary": str(hardware.cpu_logical_cores),
                    "memory_bytes": hardware.ram_total_bytes,
                    "gpu_present": hardware.gpu_present,
                    "gpu_vendor": None,
                    "gpu_name": hardware.gpu_name,
                    "gpu_memory_bytes": hardware.vram_total_bytes,
                    "capability_status": capability_status.value,
                    "safe_reason_codes": (
                        () if hardware.local_runtime_eligible else ("LOCAL_HARDWARE_NOT_VALIDATED",)
                    ),
                },
            }
        }

    def infer(
        self,
        requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"],
        prompt_ref: PromptReference,
        input_projection: Mapping[str, object],
        output_schema_ref: OutputSchemaDefinition,
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
    ) -> StructuredInferenceResultV1:
        settings = self.settings_service()
        requested = RequestedRuntimeMode(requested_mode)
        api_status = self.status_service.get_status(self.api_provider_name)
        ollama_status = self.status_service.get_status("ollama")
        approved_model = self.status_service.get_approved_model(settings.approved_model_id or "")
        hardware = self.hardware_probe.probe()
        hardware_capability = HardwareCapability(
            cpu_arch="unknown",
            core_summary=str(hardware.cpu_logical_cores),
            memory_bytes=hardware.ram_total_bytes,
            gpu_present=hardware.gpu_present,
            gpu_vendor=None,
            gpu_name=hardware.gpu_name,
            gpu_memory_bytes=hardware.vram_total_bytes,
            capability_status=(
                HardwareCapabilityStatus.VALIDATED
                if hardware.local_runtime_eligible
                else HardwareCapabilityStatus.NOT_VALIDATED
            ),
            safe_reason_codes=()
            if hardware.local_runtime_eligible
            else ("LOCAL_HARDWARE_NOT_VALIDATED",),
        )
        credential = self.credential_service.get_credential_status(self.api_provider_name)
        decision = self.decide(
            RouteDecisionInput(
                build_profile=settings.deployment_profile,
                requested_mode=requested,
                external_llm_consent=settings.external_llm_consent,
                api_credential_state=(
                    LLMCredentialState.KEYRING
                    if credential.storage_mode == "KEYRING"
                    else LLMCredentialState.SESSION_MEMORY
                    if credential.storage_mode == "SESSION_ONLY"
                    else LLMCredentialState.UNAVAILABLE
                    if credential.validation_status == "UNAVAILABLE"
                    else LLMCredentialState.NOT_CONFIGURED
                ),
                api_probe=ProbeResult(
                    availability=(
                        AvailabilityState.AVAILABLE
                        if api_status.availability == "READY"
                        else AvailabilityState.UNAVAILABLE
                    ),
                    safe_error_code=api_status.error_code,
                ),
                hardware_capability=hardware_capability,
                ollama_probe=ProbeResult(
                    availability=(
                        AvailabilityState.AVAILABLE
                        if ollama_status.availability == "READY"
                        else AvailabilityState.UNAVAILABLE
                    ),
                    safe_error_code=ollama_status.error_code,
                ),
                approved_model=approved_model,
            )
        )
        trace_context = ObservabilityContext()
        self._record_selection(
            prompt_ref=prompt_ref,
            trace_context=trace_context,
            requested_mode=requested,
            decision=decision,
        )
        provider = self._resolve_provider(
            runtime=decision.primary_runtime,
            settings=settings,
            approved_model=approved_model,
            hardware_capability=hardware_capability,
        )
        try:
            result = self._invoke_provider(
                provider=provider,
                prompt_ref=prompt_ref,
                prompt_input=input_projection,
                output_schema=output_schema_ref,
                requested_mode=requested,
                trace_context=trace_context,
                fallback_reason=None,
                semantic_validate=None,
                external_transfer_scope=external_transfer_scope,
            )
            return _canonical_result(result)
        except LLMInvocationError as error:
            if not self._should_fallback(
                error=error,
                decision=decision,
                requested_mode=requested,
                settings=settings,
            ):
                raise
            self._record_fallback_started(
                trace_context=trace_context,
                requested_mode=requested,
                decision=decision,
                error=error,
            )
            result = self._invoke_provider(
                provider=self._resolve_provider(
                    runtime=ActualRuntime.API_LLM,
                    settings=settings,
                    approved_model=approved_model,
                    hardware_capability=hardware_capability,
                ),
                prompt_ref=prompt_ref,
                prompt_input=input_projection,
                output_schema=output_schema_ref,
                requested_mode=requested,
                trace_context=trace_context,
                fallback_reason=error.code.value,
                semantic_validate=None,
                external_transfer_scope=external_transfer_scope,
            )
            self.event_recorder.record(
                event_name="LLM_FALLBACK_COMPLETED",
                severity=Severity.INFO,
                correlation=trace_context,
                attributes={
                    "requested_mode": requested.value,
                    "fallback_reason": error.code.value,
                    "actual_runtime": result.actual_runtime.value,
                    "provider": result.provider,
                    "model": result.model,
                },
                result_code="FALLBACK_COMPLETED",
                status="COMPLETED",
            )
            return _canonical_result(result)

    def decide(self, request: RouteDecisionInput) -> RouteDecision:
        """Preserved deterministic requested-mode and availability rules."""
        if request.build_profile == "API_ONLY":
            if request.requested_mode is not RequestedRuntimeMode.API_LLM:
                return _decision(ActualRuntime.API_LLM, False, "API_ONLY_MODE_BLOCKED")
            if not request.external_llm_consent:
                return _decision(ActualRuntime.API_LLM, False, "CONSENT_REQUIRED")
            return _decision(ActualRuntime.API_LLM, False, None)
        if request.requested_mode is RequestedRuntimeMode.API_LLM:
            if not request.external_llm_consent:
                return _decision(ActualRuntime.API_LLM, False, "CONSENT_REQUIRED")
            return _decision(ActualRuntime.API_LLM, False, None)
        if request.requested_mode is RequestedRuntimeMode.LOCAL_GPU:
            return _decision(ActualRuntime.LOCAL_GPU, False, _local_runtime_reason(request))
        fallback_allowed = (
            request.external_llm_consent
            and request.api_credential_state
            in {LLMCredentialState.KEYRING, LLMCredentialState.SESSION_MEMORY}
            and request.api_probe.availability
            in {AvailabilityState.AVAILABLE, AvailabilityState.UNKNOWN}
        )
        return RouteDecision(
            primary_runtime=ActualRuntime.LOCAL_GPU,
            fallback_allowed=fallback_allowed,
            fallback_target=ActualRuntime.API_LLM if fallback_allowed else None,
            safe_reason_code=_local_runtime_reason(request),
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
                    LLMErrorCode.CONSENT_REQUIRED, "external LLM consent is disabled"
                )
            if self.credential_service.read_secret(self.api_provider_name) is None:
                raise LLMInvocationError(
                    LLMErrorCode.API_KEY_MISSING, "LLM API key is not configured"
                )
            return self._api_leaf
        if hardware_capability.capability_status is not HardwareCapabilityStatus.VALIDATED:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE,
                "local hardware capability is not validated for LOCAL_GPU",
            )
        if approved_model is None:
            raise LLMInvocationError(
                LLMErrorCode.MODEL_NOT_APPROVED, "approved model is unavailable"
            )
        if settings.ollama_endpoint is None:
            raise LLMInvocationError(
                LLMErrorCode.LOCAL_UNAVAILABLE, "Ollama endpoint is not configured"
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
        semantic_validate: Callable[[object], object] | None,
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
    ) -> StructuredLLMResult:
        if provider.runtime is ActualRuntime.API_LLM:
            self._require_external_call(external_transfer_scope)
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
        api_key_bytes = (
            self.credential_service.read_secret(self.api_provider_name)
            if provider.runtime is ActualRuntime.API_LLM
            else None
        )
        api_key = None if api_key_bytes is None else api_key_bytes.decode("utf-8")
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
                external_transfer_scope=external_transfer_scope,
            )
        except ValueError as error:
            raise LLMInvocationError(LLMErrorCode.INVALID_PROVIDER_RESPONSE, str(error)) from error
        except TimeoutError as error:
            raise LLMInvocationError(
                LLMErrorCode.PROVIDER_TIMEOUT, "LLM invocation timed out", retryable=True
            ) from error
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
        external_transfer_scope: ExternalLlmTransferScopeV1 | None,
    ) -> tuple[object, int]:
        candidate = _parse_payload(payload)
        errors = _collect_validation_errors(candidate, output_schema, semantic_validate)
        if not errors:
            return candidate, 1
        if self.schema_repairer is None or self.runtime_policy.structured_output_repair_budget < 1:
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID, "structured output did not satisfy schema"
            )
        if provider.runtime is ActualRuntime.API_LLM:
            self._require_external_call(external_transfer_scope)
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
            validator_errors=tuple(errors),
        )
        if _collect_validation_errors(repaired, output_schema, semantic_validate):
            raise LLMInvocationError(
                LLMErrorCode.OUTPUT_SCHEMA_INVALID, "schema repair did not produce a valid payload"
            )
        return repaired, 2

    def _require_external_call(self, scope: ExternalLlmTransferScopeV1 | None) -> None:
        if not self.settings_service().external_llm_consent:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED, "external LLM consent is disabled"
            )
        if scope is None or self.checkpoint is None:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM transfer scope is not published",
            )
        published = self.checkpoint.load_external_llm_scope(scope.run_id)
        if published != scope:
            raise LLMInvocationError(
                LLMErrorCode.CONSENT_REQUIRED,
                "external LLM transfer scope checkpoint is stale",
            )

    def _should_fallback(
        self,
        *,
        error: LLMInvocationError,
        decision: RouteDecision,
        requested_mode: RequestedRuntimeMode,
        settings: AppSettings,
    ) -> bool:
        return (
            requested_mode is RequestedRuntimeMode.AUTO
            and settings.external_llm_consent
            and decision.fallback_allowed
            and error.code
            in {
                LLMErrorCode.LOCAL_UNAVAILABLE,
                LLMErrorCode.MODEL_NOT_FOUND,
                LLMErrorCode.MODEL_NOT_APPROVED,
                LLMErrorCode.MODEL_LOAD_FAILED,
                LLMErrorCode.GPU_OOM,
                LLMErrorCode.PROVIDER_TIMEOUT,
                LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            }
        )

    def _record_selection(
        self,
        *,
        prompt_ref: PromptReference,
        trace_context: ObservabilityContext,
        requested_mode: RequestedRuntimeMode,
        decision: RouteDecision,
    ) -> None:
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

    def _record_fallback_started(
        self,
        *,
        trace_context: ObservabilityContext,
        requested_mode: RequestedRuntimeMode,
        decision: RouteDecision,
        error: LLMInvocationError,
    ) -> None:
        self.event_recorder.record(
            event_name="LLM_FALLBACK_STARTED",
            severity=Severity.WARNING,
            correlation=trace_context,
            attributes={
                "requested_mode": requested_mode.value,
                "fallback_reason": error.code.value,
                "from_runtime": decision.primary_runtime.value,
                "to_runtime": None
                if decision.fallback_target is None
                else decision.fallback_target.value,
            },
            result_code="FALLBACK_STARTED",
            status="STARTED",
        )


def _decision(runtime: ActualRuntime, fallback_allowed: bool, reason: str | None) -> RouteDecision:
    return RouteDecision(runtime, fallback_allowed, None, reason)


def _local_runtime_reason(request: RouteDecisionInput) -> str | None:
    if request.hardware_capability.capability_status in {
        HardwareCapabilityStatus.UNKNOWN,
        HardwareCapabilityStatus.NOT_VALIDATED,
    }:
        return "LOCAL_HARDWARE_NOT_VALIDATED"
    if request.hardware_capability.capability_status is HardwareCapabilityStatus.INSUFFICIENT:
        return "LOCAL_HARDWARE_INSUFFICIENT"
    if request.approved_model is None:
        return "APPROVED_MODEL_UNAVAILABLE"
    if request.ollama_probe.safe_error_code is not None:
        return cast(str, request.ollama_probe.safe_error_code)
    if request.ollama_probe.availability is not AvailabilityState.AVAILABLE:
        return "OLLAMA_UNAVAILABLE"
    return None


def _probe_from_dict(value: object) -> ProbeResult:
    summary = cast(dict[str, object], value)
    return ProbeResult(
        availability=AvailabilityState(str(summary["availability"])),
        safe_error_code=cast(str | None, summary.get("safe_error_code")),
        last_probe_at_ms=cast(int | None, summary.get("last_probe")),
    )


def _hardware_from_dict(value: object) -> HardwareCapability:
    summary = cast(dict[str, object], value)
    return HardwareCapability(
        cpu_arch=str(summary["cpu_arch"]),
        core_summary=str(summary["core_summary"]),
        memory_bytes=cast(int | None, summary["memory_bytes"]),
        gpu_present=bool(summary["gpu_present"]),
        gpu_vendor=cast(str | None, summary["gpu_vendor"]),
        gpu_name=cast(str | None, summary["gpu_name"]),
        gpu_memory_bytes=cast(int | None, summary["gpu_memory_bytes"]),
        capability_status=HardwareCapabilityStatus(str(summary["capability_status"])),
        safe_reason_codes=tuple(cast(list[str], summary.get("safe_reason_codes", []))),
    )


def _parse_payload(payload: object) -> object:
    if isinstance(payload, str):
        import json

        return json.loads(payload)
    return payload


def _collect_validation_errors(
    candidate: object,
    output_schema: OutputSchemaDefinition,
    semantic_validate: Callable[[object], object] | None,
) -> list[str]:
    shape_errors = cast(list[str], validate_output_schema(candidate, output_schema.json_schema))
    if shape_errors or semantic_validate is None:
        return shape_errors
    try:
        semantic_validate(candidate)
    except ValueError as error:
        return [str(error)]
    return []


def _sum_tokens(input_tokens: int | None, output_tokens: int | None) -> int | None:
    if input_tokens is None and output_tokens is None:
        return None
    return (input_tokens or 0) + (output_tokens or 0)


def _canonical_result(result: StructuredLLMResult) -> StructuredInferenceResultV1:
    if not isinstance(result.structured_output, dict):
        raise LLMInvocationError(
            LLMErrorCode.OUTPUT_SCHEMA_INVALID,
            "structured inference output must be an object",
        )
    return StructuredInferenceResultV1(
        schema_version=1,
        structured_output=cast(dict[str, object], result.structured_output),
        provider=result.provider,
        model=result.model,
        actual_runtime=cast(Literal["LOCAL_GPU", "API_LLM"], result.actual_runtime.value),
        input_tokens=result.input_tokens or 0,
        output_tokens=result.output_tokens or 0,
        latency_ms=result.latency_ms,
        fallback_reason=result.fallback_reason,
    )
