"""Default hardware and Ollama probe adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass

from google_work_agent.adapters.llm.ollama.transport import OllamaTransport
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    AvailabilityState,
    OllamaRuntimeProbe,
    ProbeResult,
)


@dataclass(frozen=True, slots=True)
class LoopbackOllamaProbe(OllamaRuntimeProbe):
    transport: OllamaTransport
    timeout_seconds: int = 5

    def probe(
        self,
        *,
        endpoint: str | None,
        approved_model: ApprovedModelInfo | None,
    ) -> ProbeResult:
        if endpoint is None:
            return ProbeResult(
                availability=AvailabilityState.NOT_CONFIGURED,
                safe_error_code="OLLAMA_ENDPOINT_NOT_CONFIGURED",
            )
        result = self.transport.probe(
            endpoint=endpoint,
            model_id=None if approved_model is None else approved_model.model_id,
            timeout_seconds=self.timeout_seconds,
        )
        if result.availability is not AvailabilityState.AVAILABLE or approved_model is None:
            return result
        if approved_model.digest is not None:
            actual_digest = result.metadata.get("model_digest")
            normalized_actual = (
                str(actual_digest).removeprefix("sha256:") if actual_digest is not None else None
            )
            if normalized_actual != approved_model.digest:
                return ProbeResult(
                    availability=AvailabilityState.DEGRADED,
                    safe_error_code="MODEL_HASH_MISMATCH",
                    metadata=result.metadata,
                )
        if approved_model.minimum_runtime_version is not None:
            actual_version = _numeric_version(result.metadata.get("version"))
            minimum_version = _numeric_version(approved_model.minimum_runtime_version)
            if (
                actual_version is None
                or minimum_version is None
                or _pad_version(actual_version, minimum_version)
                < _pad_version(minimum_version, actual_version)
            ):
                return ProbeResult(
                    availability=AvailabilityState.DEGRADED,
                    safe_error_code="OLLAMA_VERSION_UNSUPPORTED",
                    metadata=result.metadata,
                )
        return result


def _numeric_version(value: object) -> tuple[int, ...] | None:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", str(value)) if value is not None else None
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _pad_version(value: tuple[int, ...], other: tuple[int, ...]) -> tuple[int, ...]:
    return value + (0,) * max(0, len(other) - len(value))
