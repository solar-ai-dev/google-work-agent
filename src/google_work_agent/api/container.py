"""Dependency contract supplied to the FastAPI delivery boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from google_work_agent.api.security.policies import DEFAULT_ENDPOINT_POLICY_REGISTRY
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.ports import (
    ApiAccessGuard,
    ClockPort,
    LauncherProbeVerifier,
    OperationalLogSink,
    ReadinessAggregator,
    RuntimeStatusProvider,
    SseEventBufferPort,
    UUIDPort,
    WorkflowRuntime,
)

API_CONTRACT_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ApiContainer:
    """Dependencies and delivery configuration assembled by the launcher."""

    unit_of_work_factory: Callable[[], Any]
    query_service: Any
    create_conversation_handler: Any
    approve_action_service: Any
    modify_action_service: Any
    reject_action_service: Any
    prepare_retry_service: Any
    cancel_run_service: Any
    resume_run_service: Any
    workflow_runtime: WorkflowRuntime
    event_publisher: SseEventBufferPort
    readiness_aggregator: ReadinessAggregator
    runtime_status_provider: RuntimeStatusProvider
    api_access_guard: ApiAccessGuard
    clock: ClockPort
    id_generator: UUIDPort
    release_version: str
    environment: str
    service_instance_id: str
    action_gateway: Any | None = None
    api_contract_version: str = API_CONTRACT_VERSION
    local_bind_host: str = "127.0.0.1"
    local_bind_port: int = 8000
    max_request_body_bytes: int = 64 * 1024
    api_docs_enabled: bool = False
    launcher_probe_verifier: LauncherProbeVerifier | None = None
    bootstrap_grant_store: Any | None = None
    local_session_manager: Any | None = None
    endpoint_policy_registry: Any = DEFAULT_ENDPOINT_POLICY_REGISTRY
    start_run_service: Any | None = None
    graph_profile: Any = "SIX_ROLE_BASELINE"
    graph_version: str = "resume-contract-v1"
    schedule_run_execution: Any | None = None
    resume_target_registry: Any | None = None
    client_address_resolver: Callable[[Request], str | None] | None = None
    operational_log_sink: OperationalLogSink | None = None
    start_authorization_handler: Any | None = None
    get_connection_status_handler: Any | None = None
    revoke_connection_handler: Any | None = None
    resource_query_service: Any | None = None
    list_task_lists_handler: Any | None = None
    list_calendars_handler: Any | None = None
    get_task_resource_detail_handler: Any | None = None
    get_calendar_resource_detail_handler: Any | None = None
    frontend_site: Any | None = None
    additional_readiness_checks: tuple[Callable[[], Any], ...] = ()
    safe_mode_controller: Any | None = None
    get_runtime_status_handler: Any | None = None
    update_runtime_mode_handler: Any | None = None
    core_initialization_in_progress: bool = False
    get_settings_handler: Any | None = None
    update_settings_handler: Any | None = None
    list_backups_handler: Any | None = None
    create_backup_handler: Any | None = None
    restore_backup_handler: Any | None = None
    create_diagnostic_bundle_handler: Any | None = None
    request_shutdown_handler: Any | None = None
    get_llm_credential_status_handler: Any | None = None
    store_llm_credential_handler: Any | None = None
    delete_llm_credential_handler: Any | None = None
    test_llm_connection_service: Any | None = None
    get_attachment_handler: Any | None = None
    create_staged_attachment_handler: Any | None = None
    list_conversations_handler: Any | None = None
    get_conversation_history_handler: Any | None = None
    project_context_preview_handler: Any | None = None
    adjust_context_handler: Any | None = None
    project_recovery_options_handler: Any | None = None
    project_error_actions_handler: Any | None = None
    project_external_llm_transfer_scope_handler: Any | None = None
    issue_selection_handle: IssueSelectionHandle | None = None
    resolve_selection_handle: ResolveSelectionHandle | None = None
    resource_connector_id: str = "google_workspace"
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    shutdown_callbacks: tuple[Callable[[], None], ...] = ()
