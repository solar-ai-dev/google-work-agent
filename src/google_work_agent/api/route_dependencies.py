"""Typed dependency surfaces exposed to FastAPI route concerns."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.api.security.bootstrap import BootstrapGrantStore
from google_work_agent.api.security.sessions import LocalSessionManager
from google_work_agent.application.attachments import (
    GetGmailAttachmentService,
    StageAttachmentService,
)
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.google_connection import (
    DisconnectGoogleService,
    GetGoogleConnectionService,
    StartGoogleOAuthService,
)
from google_work_agent.application.llm import (
    DeleteLLMApiKeyService,
    GetLLMConnectionService,
    StoreLLMApiKeyService,
    TestLLMConnectionService,
)
from google_work_agent.application.queries import QueryService
from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.application.settings import (
    CreateBackupService,
    CreateRestorePlanService,
    GetSettingsService,
    ListBackupsService,
    PatchSettingsService,
    RequestShutdownService,
)
from google_work_agent.application.start_run import (
    CreateConversationService,
    ModifyWriteActionService,
    RejectWriteActionService,
    ResumeRunService,
    StartRunService,
)
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
    ResolveMismatchRecoveryService,
)
from google_work_agent.ports import (
    Clock,
    IdGenerator,
    LauncherProbeVerifier,
    ReadinessAggregator,
    ReadinessCheckResult,
    RunEventPublisher,
    UnitOfWork,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
type RouteDependencyProvider[T] = Callable[[], T]


@dataclass(frozen=True, slots=True)
class SafeModeRouteState:
    enabled: bool
    reason_codes: tuple[str, ...]
    allowed_operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HealthRouteDependencies:
    service_instance_id: str
    release_version: str
    api_contract_version: str
    clock: Clock
    readiness_aggregator: RouteDependencyProvider[ReadinessAggregator]
    launcher_probe_verifier: LauncherProbeVerifier | None
    frontend_readiness_check: Callable[[], ReadinessCheckResult] | None
    safe_mode_readiness_check: Callable[[], ReadinessCheckResult] | None
    additional_readiness_checks: tuple[Callable[[], ReadinessCheckResult], ...]


@dataclass(frozen=True, slots=True)
class SessionRouteDependencies:
    service_instance_id: str
    api_contract_version: str
    clock: Clock
    bootstrap_grant_store: BootstrapGrantStore | None
    local_session_manager: LocalSessionManager | None


@dataclass(frozen=True, slots=True)
class GoogleRouteDependencies:
    api_contract_version: str
    start_google_oauth_service: RouteDependencyProvider[StartGoogleOAuthService | None]
    get_google_connection_service: RouteDependencyProvider[GetGoogleConnectionService | None]
    disconnect_google_service: RouteDependencyProvider[DisconnectGoogleService | None]


@dataclass(frozen=True, slots=True)
class RuntimeRouteDependencies:
    api_contract_version: str
    query_service: RouteDependencyProvider[QueryService]
    safe_mode_state: Callable[[], SafeModeRouteState | None]


@dataclass(frozen=True, slots=True)
class IdentityRouteDependencies:
    api_contract_version: str
    query_service: RouteDependencyProvider[QueryService]


@dataclass(frozen=True, slots=True)
class ConversationRouteDependencies:
    api_contract_version: str
    query_service: RouteDependencyProvider[QueryService]
    create_conversation_service: RouteDependencyProvider[CreateConversationService]


@dataclass(frozen=True, slots=True)
class RunRouteDependencies:
    api_contract_version: str
    query_service: RouteDependencyProvider[QueryService]
    start_run_service: RouteDependencyProvider[StartRunService]
    cancel_run_service: RouteDependencyProvider[RequestRunCancellationService]
    resume_run_service: RouteDependencyProvider[ResumeRunService]
    resolve_recovery_service: RouteDependencyProvider[ResolveMismatchRecoveryService]
    local_run_coordinator: LocalRunCoordinator
    id_generator: IdGenerator


@dataclass(frozen=True, slots=True)
class ActionRouteDependencies:
    api_contract_version: str
    approve_action_service: RouteDependencyProvider[ApproveWriteActionService]
    modify_action_service: RouteDependencyProvider[ModifyWriteActionService]
    reject_action_service: RouteDependencyProvider[RejectWriteActionService]
    prepare_retry_service: RouteDependencyProvider[PrepareWriteRetryService]
    unit_of_work_factory: UnitOfWorkFactory
    local_run_coordinator: LocalRunCoordinator
    event_publisher: RouteDependencyProvider[RunEventPublisher]
    clock: Clock
    id_generator: IdGenerator


@dataclass(frozen=True, slots=True)
class EventRouteDependencies:
    api_contract_version: str
    query_service: RouteDependencyProvider[QueryService]
    event_publisher: RouteDependencyProvider[RunEventPublisher]
    clock: Clock


@dataclass(frozen=True, slots=True)
class ResourceRouteDependencies:
    api_contract_version: str
    resource_query_service: RouteDependencyProvider[ResourceQueryService | None]


@dataclass(frozen=True, slots=True)
class SettingsRouteDependencies:
    api_contract_version: str
    get_settings_service: RouteDependencyProvider[GetSettingsService | None]
    patch_settings_service: RouteDependencyProvider[PatchSettingsService | None]
    list_backups_service: RouteDependencyProvider[ListBackupsService | None]
    create_backup_service: RouteDependencyProvider[CreateBackupService | None]
    create_restore_plan_service: RouteDependencyProvider[CreateRestorePlanService | None]
    request_shutdown_service: RouteDependencyProvider[RequestShutdownService | None]


@dataclass(frozen=True, slots=True)
class LLMRouteDependencies:
    api_contract_version: str
    get_llm_connection_service: RouteDependencyProvider[GetLLMConnectionService | None]
    store_llm_api_key_service: RouteDependencyProvider[StoreLLMApiKeyService | None]
    delete_llm_api_key_service: RouteDependencyProvider[DeleteLLMApiKeyService | None]
    test_llm_connection_service: RouteDependencyProvider[TestLLMConnectionService | None]


@dataclass(frozen=True, slots=True)
class AttachmentRouteDependencies:
    api_contract_version: RouteDependencyProvider[str]
    get_gmail_attachment_service: RouteDependencyProvider[GetGmailAttachmentService | None]
    stage_attachment_service: RouteDependencyProvider[StageAttachmentService | None]
