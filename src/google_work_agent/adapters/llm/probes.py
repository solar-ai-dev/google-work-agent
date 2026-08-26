"""Default hardware and Ollama probe adapters."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.adapters.llm.ollama import OllamaTransport
from google_work_agent.ports import (
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
        return self.transport.probe(
            endpoint=endpoint,
            model_id=None if approved_model is None else approved_model.model_id,
            timeout_seconds=self.timeout_seconds,
        )
