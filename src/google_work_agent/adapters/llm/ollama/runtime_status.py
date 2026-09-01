"""Canonical Ollama runtime-status leaf."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.llm.llm_runtime_status_port import LlmProviderRuntimeStatus
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    AvailabilityState,
    OllamaRuntimeProbe,
)


@dataclass(frozen=True, slots=True)
class OllamaLlmRuntimeStatusAdapter:
    probe: OllamaRuntimeProbe

    def get_status(
        self,
        *,
        endpoint: str | None,
        model: ApprovedModelInfo | None,
    ) -> LlmProviderRuntimeStatus:
        if endpoint is None or model is None:
            return LlmProviderRuntimeStatus(
                schema_version=1,
                provider="ollama",
                configured=False,
                availability="DISABLED",
                model_id=None if model is None else model.model_id,
                error_code="LOCAL_RUNTIME_NOT_CONFIGURED",
            )
        result = self.probe.probe(endpoint=endpoint, approved_model=model)
        return LlmProviderRuntimeStatus(
            schema_version=1,
            provider="ollama",
            configured=True,
            availability=(
                "READY" if result.availability is AvailabilityState.AVAILABLE else "UNAVAILABLE"
            ),
            model_id=model.model_id,
            error_code=result.safe_error_code,
        )


__all__ = ["OllamaLlmRuntimeStatusAdapter"]
