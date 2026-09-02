"""Exact LLM runtime value fixtures shared by tests."""

from __future__ import annotations

from google_work_agent.ports.llm.runtime_selection import (
    LlmRuntimeSelectionV1,
    LocalRuntimeActivationStatus,
    LocalRuntimeRequirementsV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo
from google_work_agent.ports.system.settings_port import PanelPreferencesV1, SettingsViewV1


def settings_view(
    *,
    preferred_llm_mode: str = "AUTO",
    external_llm_consent: bool = True,
) -> SettingsViewV1:
    return SettingsViewV1(
        schema_version=1,
        timezone="Asia/Seoul",
        default_tasklist_id=None,
        default_calendar_id=None,
        preferred_llm_mode=preferred_llm_mode,  # type: ignore[arg-type]
        external_llm_consent=external_llm_consent,
        retention_days=30,
        theme="LIGHT",
        panel_preferences=PanelPreferencesV1(1, True, "CONVERSATIONS"),
        working_day_start_local="09:00",
        working_day_end_local="18:00",
        include_weekends=False,
        calendar_buffer_minutes=0,
        max_run_execution_ms=60_000,
        max_connector_calls_per_run=20,
        max_source_page_calls_per_run=10,
        max_detail_fetches_per_run=10,
        max_context_tokens_per_run=8_000,
        max_retry_attempts_per_run=1,
        circuit_failure_threshold=3,
        circuit_open_duration_ms=30_000,
    )


def runtime_selection(
    *,
    deployment_profile: str,
    model: ApprovedModelInfo | None = None,
    release_version: str = "test-release",
) -> LlmRuntimeSelectionV1:
    active = deployment_profile == "LOCAL_CAPABLE" and model is not None
    return LlmRuntimeSelectionV1(
        schema_version=1,
        deployment_profile=deployment_profile,  # type: ignore[arg-type]
        selected_model=model if active else None,
        ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
        model_manifest_hash="1" * 64 if active else None,
        product_decision_hash="2" * 64 if active else None,
        local_runtime_activation_status=(
            LocalRuntimeActivationStatus.ACTIVE
            if active
            else LocalRuntimeActivationStatus.DISABLED_BY_DEPLOYMENT_PROFILE
            if deployment_profile == "API_ONLY"
            else LocalRuntimeActivationStatus.DEFERRED_UNTIL_PRODUCT_DECISION
        ),
        requirements=(
            LocalRuntimeRequirementsV1(1, 1, 1, "WINDOWS", "AMD64")
            if active
            else None
        ),
        release_version=release_version,
    )


__all__ = ["runtime_selection", "settings_view"]
