"""Gemini provider-private runtime status leaf."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.adapters.llm.gemini.structured_inference import GeminiConnectionService
from google_work_agent.ports import AvailabilityState
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusV1


@dataclass(frozen=True, slots=True)
class GeminiLlmRuntimeStatusAdapter:
    provider: str
    connection: GeminiConnectionService

    def get_status(self, *, api_key: str | None, timeout_seconds: int) -> LlmRuntimeStatusV1:
        probe = self.connection.probe(api_key=api_key, timeout_seconds=timeout_seconds)
        return LlmRuntimeStatusV1(
            schema_version=1,
            provider=self.provider,
            configured=api_key is not None,
            availability=(
                "READY" if probe.availability is AvailabilityState.AVAILABLE else "UNAVAILABLE"
            ),
            model_id=None,
            error_code=probe.safe_error_code,
        )


__all__ = ["GeminiLlmRuntimeStatusAdapter"]
