"""Project the session-visible runtime summary through Application authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class GetRuntimeSummaryQuery:
    """Read-only runtime summary request."""


@dataclass(frozen=True, slots=True)
class GetRuntimeSummaryResult:
    """Allowlisted runtime projection for the Local API."""

    summary: dict[str, object]


class GetRuntimeSummaryHandler:
    """Own runtime projection composition without exposing secret material."""

    def __init__(
        self,
        *,
        query_service_factory: Callable[[], Any],
        safe_mode_state: Callable[[], Any | None],
    ) -> None:
        self._query_service_factory = query_service_factory
        self._safe_mode_state = safe_mode_state

    def handle(self, query: GetRuntimeSummaryQuery) -> GetRuntimeSummaryResult:
        del query
        source = self._query_service_factory().get_runtime_summary()
        safe_mode = source.safe_mode
        reason_codes = list(source.safe_mode_reason_codes)
        allowed_operations = list(source.allowed_operations)
        safe_mode_state = self._safe_mode_state()
        if safe_mode_state is not None:
            safe_mode = safe_mode_state.enabled
            reason_codes = list(safe_mode_state.reason_codes)
            allowed_operations = list(safe_mode_state.allowed_operations)
        return GetRuntimeSummaryResult(
            summary={
                "google": source.google,
                "mcp": source.mcp,
                "api_llm": source.api_llm,
                "ollama": source.ollama,
                "deployment_profile": source.deployment_profile,
                "recovery_required_run_ids": list(source.recovery_required_run_ids),
                "open_run_ids": list(source.open_run_ids),
                "google_connection": source.google_connection,
                "mcp_runtime": source.mcp_runtime,
                "llm": source.llm,
                "safe_mode": safe_mode,
                "safe_mode_reason_codes": reason_codes,
                "allowed_operations": allowed_operations,
            }
        )
