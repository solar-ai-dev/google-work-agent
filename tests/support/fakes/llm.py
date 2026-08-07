"""Fake LLM transports, probes, and repair helpers."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import cast

from google_work_agent.ports import (
    ApprovedModelInfo,
    AvailabilityState,
    HardwareCapability,
    HardwareCapabilityStatus,
    OutputSchemaDefinition,
    ProbeResult,
    PromptReference,
    ProviderResponsePayload,
)


@dataclass
class FakeAPIProviderTransport:
    probe_result: ProbeResult = field(
        default_factory=lambda: ProbeResult(availability=AvailabilityState.AVAILABLE)
    )
    invocations: list[dict[str, object]] = field(default_factory=list)
    queued_payloads: deque[object] = field(default_factory=deque)

    def probe(self, *, api_key: str, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {"kind": "probe", "api_key_length": len(api_key), "timeout_seconds": timeout_seconds}
        )
        return self.probe_result

    def invoke_structured(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
        api_key: str,
    ) -> ProviderResponsePayload:
        self.invocations.append(
            {
                "kind": "invoke",
                "prompt_id": prompt_ref.prompt_id,
                "timeout_seconds": timeout_seconds,
                "api_key_length": len(api_key),
                "prompt_input": dict(prompt_input),
                "schema_version": output_schema.schema_version,
            }
        )
        payload = self.queued_payloads.popleft()
        if isinstance(payload, Exception):
            raise payload
        return cast(ProviderResponsePayload, payload)


@dataclass
class FakeOllamaTransport:
    probe_result: ProbeResult = field(
        default_factory=lambda: ProbeResult(availability=AvailabilityState.AVAILABLE)
    )
    invocations: list[dict[str, object]] = field(default_factory=list)
    queued_payloads: deque[object] = field(default_factory=deque)

    def probe(self, *, endpoint: str, model_id: str | None, timeout_seconds: int) -> ProbeResult:
        self.invocations.append(
            {
                "kind": "probe",
                "endpoint": endpoint,
                "model_id": model_id,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.probe_result

    def invoke_structured(
        self,
        *,
        endpoint: str,
        model_id: str,
        prompt_ref: PromptReference,
        prompt_input: Mapping[str, object],
        output_schema: OutputSchemaDefinition,
        timeout_seconds: int,
    ) -> ProviderResponsePayload:
        self.invocations.append(
            {
                "kind": "invoke",
                "endpoint": endpoint,
                "model_id": model_id,
                "prompt_id": prompt_ref.prompt_id,
                "prompt_input": dict(prompt_input),
                "schema_version": output_schema.schema_version,
                "timeout_seconds": timeout_seconds,
            }
        )
        payload = self.queued_payloads.popleft()
        if isinstance(payload, Exception):
            raise payload
        return cast(ProviderResponsePayload, payload)


@dataclass(frozen=True, slots=True)
class FakeHardwareProbe:
    capability: HardwareCapability = HardwareCapability(
        cpu_arch="x86_64",
        core_summary="8",
        memory_bytes=16 * 1024 * 1024 * 1024,
        gpu_present=True,
        gpu_vendor="NVIDIA",
        gpu_name="Test GPU",
        gpu_memory_bytes=8 * 1024 * 1024 * 1024,
        capability_status=HardwareCapabilityStatus.VALIDATED,
        safe_reason_codes=(),
    )

    def probe(self) -> HardwareCapability:
        return self.capability


@dataclass
class FakeSchemaRepairer:
    repaired_output: object
    calls: list[dict[str, object]] = field(default_factory=list)

    def repair(
        self,
        *,
        prompt_ref: PromptReference,
        failed_output: object,
        output_schema: OutputSchemaDefinition,
        attempt_no: int,
        failure_reason_code: str,
    ) -> object:
        self.calls.append(
            {
                "prompt_id": prompt_ref.prompt_id,
                "attempt_no": attempt_no,
                "failure_reason_code": failure_reason_code,
                "failed_output": failed_output,
                "schema_version": output_schema.schema_version,
            }
        )
        return self.repaired_output


def approved_model(model_id: str = "approved-model") -> ApprovedModelInfo:
    return ApprovedModelInfo(
        model_id=model_id,
        runtime="OLLAMA",
        manifest_version="1",
        schema_version="1",
        minimum_runtime_version="0.1.0",
    )
