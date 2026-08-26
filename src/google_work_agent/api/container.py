"""Dependency contract supplied to the FastAPI delivery boundary."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import Request

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.api.security.policies import DEFAULT_ENDPOINT_POLICY_REGISTRY
from google_work_agent.application.resource_continuation import OpaqueResourceQueryService
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.ports import (
    ApiAccessGuard,
    ClockPort,
    UUIDPort,
    LauncherProbeVerifier,
    OperationalLogSink,
    ReadinessAggregator,
    SseEventBufferPort,
    RuntimeStatusProvider,
    WorkflowRuntime,
)

if TYPE_CHECKING:
    from google_work_agent.application.attachments import (
        GetGmailAttachmentService,
        StageAttachmentService,
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
    local_run_coordinator: Any
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
    start_google_oauth_service: Any | None = None
    get_google_connection_service: Any | None = None
    disconnect_google_service: Any | None = None
    resource_query_service: Any | None = None
    frontend_site: Any | None = None
    additional_readiness_checks: tuple[Callable[[], Any], ...] = ()
    safe_mode_controller: Any | None = None
    core_initialization_in_progress: bool = False
    get_settings_service: Any | None = None
    patch_settings_service: Any | None = None
    list_backups_service: Any | None = None
    create_backup_service: Any | None = None
    create_restore_plan_service: Any | None = None
    request_shutdown_service: Any | None = None
    get_llm_connection_service: Any | None = None
    store_llm_api_key_service: Any | None = None
    delete_llm_api_key_service: Any | None = None
    test_llm_connection_service: Any | None = None
    get_gmail_attachment_service: GetGmailAttachmentService | None = None
    stage_attachment_service: StageAttachmentService | None = None
    list_conversations_handler: Any | None = None
    get_conversation_history_handler: Any | None = None
    issue_selection_handle: IssueSelectionHandle | None = None
    resolve_selection_handle: ResolveSelectionHandle | None = None
    resource_connector_id: str = "google_workspace"
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    shutdown_callbacks: tuple[Callable[[], None], ...] = ()

    def __post_init__(self) -> None:
        if self.resume_target_registry is None:
            object.__setattr__(
                self,
                "resume_target_registry",
                ResumeTargetRegistry(
                    node_registry=NodeRegistry(graph_version=self.graph_version),
                    graph_version=self.graph_version,
                ),
            )
        if self.issue_selection_handle is None or self.resolve_selection_handle is None:
            signing_secret = secrets.token_bytes(32)
            object.__setattr__(
                self,
                "issue_selection_handle",
                IssueSelectionHandle(
                    signing_secret=signing_secret,
                    service_instance_id=self.service_instance_id,
                    now_ms=self.clock.now_ms,
                    ttl_ms=5 * 60 * 1000,
                ),
            )
            object.__setattr__(
                self,
                "resolve_selection_handle",
                ResolveSelectionHandle(
                    signing_secret=signing_secret,
                    service_instance_id=self.service_instance_id,
                    now_ms=self.clock.now_ms,
                ),
            )
        service = self.resource_query_service
        if service is not None and not isinstance(service, OpaqueResourceQueryService):
            object.__setattr__(
                self,
                "resource_query_service",
                OpaqueResourceQueryService(service),
            )
