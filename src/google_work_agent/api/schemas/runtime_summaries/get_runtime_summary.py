"""Canonical bounded Runtime Detail wire contract."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class ComponentCircuitKeyV1(ApiModel):
    schema_version: Literal[1]
    kind: Literal["CONNECTOR", "LLM_RUNTIME"]
    connector_id: str | None
    llm_runtime: Literal["API_LLM", "LOCAL_GPU"] | None


class ConnectorRuntimeStatusV1(ApiModel):
    schema_version: Literal[1]
    connector_id: str
    connection_status: Literal[
        "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
    ]
    account_ref: str | None
    scope_status: Literal["READY", "INSUFFICIENT", "UNKNOWN"]
    retry_at_ms: int | None


class LlmRuntimeStatusV1(ApiModel):
    schema_version: Literal[1]
    provider: str
    configured: bool
    availability: Literal["READY", "UNAVAILABLE", "DISABLED"]
    model_id: str | None
    error_code: str | None


class ComponentCircuitStatusV1(ApiModel):
    schema_version: Literal[1]
    key: ComponentCircuitKeyV1
    state: Literal["CLOSED", "OPEN"]
    retry_at_ms: int | None


class RunBudgetSummaryV1(ApiModel):
    schema_version: Literal[1]
    profile: Literal["NORMAL", "RETRIEVAL_HEAVY", "REVISION_HEAVY"]
    llm_calls_used: int
    llm_call_limit: int
    connector_calls_used: int
    max_connector_calls: int
    source_page_calls_used: int
    max_source_page_calls: int
    detail_fetches_used: int
    max_detail_fetches: int
    context_tokens_used: int
    max_context_tokens: int
    retry_attempts_used: int
    max_retry_attempts: int
    elapsed_ms: int
    max_execution_ms: int


class RuntimeModeStatusV1(ApiModel):
    schema_version: Literal[1]
    requested_mode: Literal["AUTO", "LOCAL_GPU", "API_LLM"]
    actual_runtime: Literal["LOCAL_GPU", "API_LLM", "MIXED"] | None
    fallback_reason: str | None


class RuntimeDetailResponseV1(ApiModel):
    schema_version: Literal[1]
    service_instance_id: str
    connectors: list[ConnectorRuntimeStatusV1]
    llm_providers: list[LlmRuntimeStatusV1]
    component_circuits: list[ComponentCircuitStatusV1]
    active_run_budget: RunBudgetSummaryV1 | None
    recovery_required: bool
    release_version: str
    frontend_build_version: str
    api_contract_version: str
    deployment_profile: str
    runtime_mode: RuntimeModeStatusV1
    database_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    migration_status: Literal["READY", "PENDING", "FAILED"]
    sse_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    recent_sanitized_error_code: str | None
    launcher_status: Literal["READY", "DEGRADED", "UNAVAILABLE"]
    manifest_status: Literal["VALID", "INVALID", "UNAVAILABLE"]
    session_status: Literal["ESTABLISHED", "NOT_ESTABLISHED"]
    safe_mode: bool
    last_backup_status: str | None
    last_migration_status: str | None


__all__ = ["RuntimeDetailResponseV1", "RuntimeModeStatusV1"]
