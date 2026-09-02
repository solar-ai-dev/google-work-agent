"""Single concrete production composition authority."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    GoogleWorkspaceConnector,
    build_google_workspace_connector_descriptor,
    google_workspace_internal_read_binding,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.load_installed_connector_manifest import (
    InstalledConnectorManifestV1,
    load_installed_connector_manifest,
)
from google_work_agent.adapters.connectors.runtime.mcp_connector_read import McpConnectorReadAdapter
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    StdioMCPClientAdapter,
    build_manifest_payload_for_descriptors,
    calculate_file_sha256,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
    keyring_service_name,
)
from google_work_agent.adapters.langgraph.checkpoint_control import (
    LangGraphCheckpointControlAdapter,
)
from google_work_agent.adapters.langgraph.main.application_services import (
    WorkflowApplicationServices,
    WorkflowRuntimeHooks,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.validate_planning_output import (
    CanonicalDomainValidationService,
)
from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.registry.checkpoint_target_resolver import (
    NativeCheckpointTargetResolver,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.llm.gemini.structured_inference import (
    GeminiConnectionService,
    GeminiStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.gemini.transport import (
    DEFAULT_GEMINI_MODEL_ID,
    GeminiHTTPClient,
)
from google_work_agent.adapters.llm.ollama.structured_inference import (
    OllamaStructuredInferenceAdapter,
)
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.adapters.llm.probes import LoopbackOllamaProbe
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    LlmCredentialRouter,
    SessionMemorySecretStore,
)
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.adapters.llm.runtime.prompt_repair_schema_repairer import (
    PromptRepairSchemaRepairer,
)
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations, discover_migrations
from google_work_agent.adapters.persistence.persistence_exceptions import MigrationError
from google_work_agent.adapters.persistence.sqlite.connected_account_store import (
    sqlite_connected_account_store_factory,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_read_unit_of_work_factory,
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.readiness.local_service_readiness import (
    LocalServiceReadinessAggregator,
)
from google_work_agent.adapters.runtime.safe_mode import SafeModeController
from google_work_agent.adapters.system.default_browser_launcher import DefaultBrowserLauncherAdapter
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    ATTACHMENT_STAGING_DIR_ENV,
    MAX_STAGED_FILE_BYTES,
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.filesystem_diagnostics import FilesystemDiagnosticsAdapter
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.json_settings import FileSettingsStore, JsonSettingsAdapter
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.adapters.system.process_component_circuit_state import (
    ProcessComponentCircuitStateAdapter,
)
from google_work_agent.adapters.system.process_maintenance_gate import (
    ProcessMaintenanceGateAdapter,
)
from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter
from google_work_agent.adapters.system.process_shutdown import ProcessShutdownAdapter
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.adapters.system.system_clock import SystemClockAdapter
from google_work_agent.adapters.system.uuid4 import Uuid4Adapter
from google_work_agent.adapters.system.windows_hardware_probe import WindowsHardwareProbeAdapter
from google_work_agent.adapters.system.workflow_handoff_reconciliation_loop import (
    WorkflowHandoffReconciliationLoop,
)
from google_work_agent.adapters.system.workflow_outcome_projector import WorkflowOutcomeProjector
from google_work_agent.api.container import API_CONTRACT_VERSION, ApiContainer
from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import (
    InactivePromptArtifactError,
    PromptRegistry,
    default_prompt_manifest_path,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.approve_action import ApproveActionHandler
from google_work_agent.application.use_cases.action.calendar_conflict_policy import (
    CalendarWorkHours,
)
from google_work_agent.application.use_cases.action.cancel_pending_action import (
    CancelPendingActionHandler,
)
from google_work_agent.application.use_cases.action.claim_read_action import ClaimReadActionHandler
from google_work_agent.application.use_cases.action.complete_read_action import (
    CompleteReadActionHandler,
)
from google_work_agent.application.use_cases.action.fail_read_action import FailReadActionHandler
from google_work_agent.application.use_cases.action.finalize_read_action import (
    FinalizeReadActionHandler,
)
from google_work_agent.application.use_cases.action.modify_action import ModifyActionHandler
from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryHandler,
)
from google_work_agent.application.use_cases.action.refresh_expired_action import (
    RefreshExpiredActionHandler,
)
from google_work_agent.application.use_cases.action.reject_action import RejectActionHandler
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
)
from google_work_agent.application.use_cases.approval.expire_approval import (
    ExpireApprovalHandler,
)
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentHandler,
)
from google_work_agent.application.use_cases.attachment.get_attachment import (
    GetAttachmentHandler,
)
from google_work_agent.application.use_cases.backup.create_backup import CreateBackupHandler
from google_work_agent.application.use_cases.backup.list_backups import ListBackupsHandler
from google_work_agent.application.use_cases.backup.restore_backup import RestoreBackupHandler
from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
)
from google_work_agent.application.use_cases.claim.claim_execution import ClaimExecutionHandler
from google_work_agent.application.use_cases.component_circuit.check_component_circuit import (
    CheckComponentCircuitHandler,
    CheckComponentCircuitQueryV1,
    CircuitProtectedConnectorReadPort,
    CircuitProtectedConnectorWritePort,
)
from google_work_agent.application.use_cases.component_circuit.record_component_call_result import (
    RecordComponentCallResultCommandV1,
    RecordComponentCallResultHandler,
)
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
    GetConnectionStatusQuery,
)
from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionHandler,
)
from google_work_agent.application.use_cases.connection.start_authorization import (
    StartAuthorizationHandler,
)
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
)
from google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle import (
    CreateDiagnosticBundleHandler,
)
from google_work_agent.application.use_cases.execution_attempt import (
    reconcile_inflight_executions as inflight_reconciliation,
)
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionHandler,
)
from google_work_agent.application.use_cases.execution_attempt.begin_execution_attempt import (
    BeginExecutionAttemptHandler,
)
from google_work_agent.application.use_cases.execution_attempt.classify_dispatch_result import (
    ClassifyDispatchResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.connector_write_projection import (
    ConnectorWriteProjection,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_failed import (
    MarkFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
)
from google_work_agent.application.use_cases.execution_attempt.store_success import (
    StoreSuccessHandler,
)
from google_work_agent.application.use_cases.llm_credential.delete_llm_credential import (
    DeleteLlmCredentialHandler,
)
from google_work_agent.application.use_cases.llm_credential.get_llm_credential_status import (
    GetLlmCredentialStatusHandler,
)
from google_work_agent.application.use_cases.llm_credential.store_llm_credential import (
    StoreLlmCredentialHandler,
)
from google_work_agent.application.use_cases.plan.publish_plan import PublishPlanHandler
from google_work_agent.application.use_cases.plan.publish_read_only_plan import (
    PublishReadOnlyPlanHandler,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultHandler,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.resource.connector_resource_access import (
    ConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.get_calendar_resource_detail import (
    GetCalendarResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.get_resource_count import (
    GetResourceCountHandler,
)
from google_work_agent.application.use_cases.resource.get_resource_detail import (
    GetResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.get_task_resource_detail import (
    GetTaskResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.list_calendars import ListCalendarsHandler
from google_work_agent.application.use_cases.resource.list_resources import ListResourcesHandler
from google_work_agent.application.use_cases.resource.list_task_lists import ListTaskListsHandler
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    LocalResourceContinuationStore,
    OpaqueConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.resource_ref.resolve_resource_ref import (
    ResolveResourceRefHandler,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    account_provider_dispatch,
    current_provider_dispatch_run_id,
)
from google_work_agent.application.use_cases.run.adjust_context import AdjustContextHandler
from google_work_agent.application.use_cases.run.begin_planning import BeginPlanningHandler
from google_work_agent.application.use_cases.run.begin_retrieval import BeginRetrievalHandler
from google_work_agent.application.use_cases.run.begin_verification import (
    BeginVerificationHandler,
)
from google_work_agent.application.use_cases.run.block_run import BlockRunHandler
from google_work_agent.application.use_cases.run.build_terminal_message import (
    BuildTerminalMessageHandler,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.complete_read_only_run import (
    CompleteReadOnlyRunHandler,
)
from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunHandler,
)
from google_work_agent.application.use_cases.run.confirm_run import ConfirmRunHandler
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionHandler,
)
from google_work_agent.application.use_cases.run.finalize_cancel import FinalizeCancelHandler
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetExecutionContextQuery,
    GetRunSnapshotHandler,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
)
from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
    ProjectExternalLlmTransferScopeQueryV1,
)
from google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart import (
    ReconcileRetrievalCacheRestartHandler,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.request_cancel import RequestCancelHandler
from google_work_agent.application.use_cases.run.request_confirmation import (
    RequestConfirmationHandler,
)
from google_work_agent.application.use_cases.run.require_reauth import RequireReauthHandler
from google_work_agent.application.use_cases.run.resume_after_reauth import (
    ResumeAfterReauthHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
    ResumeTargetIssuer,
)
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    ResumeSafeCheckpointHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    CheckpointEffectiveBindingResolver,
    ScheduleRunExecutionHandler,
)
from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisHandler
from google_work_agent.application.use_cases.run.start_run import StartRunHandler
from google_work_agent.application.use_cases.runtime_mode.update_runtime_mode import (
    UpdateRuntimeModeHandler,
)
from google_work_agent.application.use_cases.runtime_status.get_runtime_status import (
    GetRuntimeStatusHandler,
)
from google_work_agent.application.use_cases.setting.get_settings import GetSettingsHandler
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsHandler
from google_work_agent.application.use_cases.shutdown.request_shutdown import (
    RequestShutdownHandler,
)
from google_work_agent.application.use_cases.sse_event.list_run_events import ListRunEventsHandler
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventHandler,
)
from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventHandler,
)
from google_work_agent.application.use_cases.verification.store_verification import (
    StoreVerificationHandler,
)
from google_work_agent.application.use_cases.verification.verify_effect import (
    VerifyEffectHandler,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.connector.connector_write_port import ConnectorWritePort
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort, MCPClientPortError
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthConnectionMetadata,
    OAuthCredentialPort,
    OAuthEnvironment,
)
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.llm.approved_model_manifest import ModelManifestV1
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialPort
from google_work_agent.ports.llm.llm_runtime_status_port import (
    LlmProviderRuntimeStatus,
    LlmRuntimeStatusPort,
)
from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)
from google_work_agent.ports.llm.runtime_selection import (
    LlmRuntimeSelectionV1,
    LocalRuntimeActivationStatus,
    LocalRuntimeRequirementsV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    ActualRuntime,
    ApprovedModelInfo,
    LLMErrorCode,
    LLMInvocationError,
    RuntimePolicy,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.artifact_signature_verifier import ArtifactSignatureDecision
from google_work_agent.ports.system.attachment_staging_port import AttachmentStagingPort
from google_work_agent.ports.system.backup_port import BackupPort
from google_work_agent.ports.system.browser_launcher_port import BrowserLauncherPort
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.clock_port import ClockPort
from google_work_agent.ports.system.component_circuit_state_port import (
    ComponentCircuitKey,
    ComponentCircuitStatePort,
)
from google_work_agent.ports.system.contracts.approval_policy_config import (
    ApprovalPolicyConfigV1,
)
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCancelRequest,
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    RegisteredResumeTargetRefV2,
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffV1,
)
from google_work_agent.ports.system.diagnostics_port import DiagnosticsPort
from google_work_agent.ports.system.hardware_probe_port import HardwareProbePort
from google_work_agent.ports.system.launcher_probe_port import LauncherProbeDecision
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.readiness_port import (
    ReadinessAggregator,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort
from google_work_agent.ports.system.runtime_mode_port import RuntimeModePort
from google_work_agent.ports.system.settings_port import SettingsPort
from google_work_agent.ports.system.shutdown_port import ShutdownPort
from google_work_agent.ports.system.sse_event_buffer_port import SseEventBufferPort
from google_work_agent.ports.system.uuid_port import UUIDPort
from google_work_agent.ports.system.workflow_execution_port import WorkflowExecutionPort

LOGGER = logging.getLogger(__name__)

# 16/07's closed table has exactly one P0 concrete binding per outbound Port.
# Constructors stay at the outer launcher because their environment-specific
# arguments (paths, process handles, provider configuration) are not Core
# concerns; this composition root is the single selection authority.
NON_PERSISTENCE_P0_BINDINGS: tuple[tuple[type[object], type[object]], ...] = (
    (ConnectorReadPort, McpConnectorReadAdapter),
    (ConnectorWritePort, McpConnectorWriteAdapter),
    (OAuthCredentialPort, McpOAuthCredentialAdapter),
    (MCPClientPort, StdioMCPClientAdapter),
    (StructuredInferencePort, StructuredInferenceRuntimeRouter),
    (LlmCredentialPort, LlmCredentialRouter),
    (LlmRuntimeStatusPort, LlmRuntimeStatusRouter),
    (SecretStorePort, OsKeyringSecretStoreAdapter),
    (CheckpointPort, SqliteCheckpointAdapter),
    (RunRetrievalCachePort, InMemoryRunRetrievalCache),
    (WorkflowExecutionPort, BackgroundRunExecutorAdapter),
    (SettingsPort, JsonSettingsAdapter),
    (RuntimeModePort, ProcessRuntimeModeAdapter),
    (BackupPort, FilesystemBackupAdapter),
    (DiagnosticsPort, FilesystemDiagnosticsAdapter),
    (ShutdownPort, ProcessShutdownAdapter),
    (OperationalCommandReplayPort, FilesystemOperationalCommandReplayAdapter),
    (AttachmentStagingPort, FilesystemAttachmentStagingAdapter),
    (ClockPort, SystemClockAdapter),
    (UUIDPort, Uuid4Adapter),
    (HardwareProbePort, WindowsHardwareProbeAdapter),
    (BrowserLauncherPort, DefaultBrowserLauncherAdapter),
    (ComponentCircuitStatePort, ProcessComponentCircuitStateAdapter),
    (SseEventBufferPort, InMemorySseEventBuffer),
)


@dataclass(frozen=True, slots=True)
class ProductionRuntime:
    checkpoint: SqliteCheckpointAdapter
    reconcile_inflight_executions: inflight_reconciliation.ReconcileInflightExecutionsHandler
    workflow_execution: BackgroundRunExecutorAdapter
    schedule_run_execution: ScheduleRunExecutionHandler
    redrive_workflow_handoffs: RedriveWorkflowHandoffsHandler
    workflow_handoff_reconciliation_loop: WorkflowHandoffReconciliationLoop


def _build_require_recovery(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    checkpoint: SqliteCheckpointAdapter,
    now_ms: Callable[[], int],
    resume_target_registry: ResumeTargetIssuer | None = None,
) -> RequireRecoveryHandler:
    return RequireRecoveryHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        resume_target_registry=resume_target_registry,
    )


def _build_workflow_application_services(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    get_run_snapshot: GetRunSnapshotHandler,
    connector_reader: ConnectorReadProjection,
    tool_catalog: SignedToolRegistry,
    now_ms: Callable[[], int],
    id_factory: Callable[[], str],
    service_instance_id: str,
    checkpoint: CheckpointPort,
    resume_target_registry: ResumeTargetRegistry,
    runtime_hooks: WorkflowRuntimeHooks,
    claim_context_signer: Callable[[dict[str, object]], str] | None,
    work_hours_provider: Callable[[], CalendarWorkHours],
    sse_event_buffer: SseEventBufferPort | None,
    environment: str,
    release_version: str,
) -> WorkflowApplicationServices:
    start_analysis = StartAnalysisHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    build_terminal_message = BuildTerminalMessageHandler()
    emit_terminal_trace = EmitTraceEventHandler(
        unit_of_work_factory=unit_of_work_factory,
        environment=environment,
        release_version=release_version,
    )
    project_terminal_event = (
        None if sse_event_buffer is None else ProjectRunEventHandler(sse_event_buffer)
    )
    begin_retrieval = BeginRetrievalHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    begin_planning = BeginPlanningHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        id_factory=id_factory,
        resume_target_registry=resume_target_registry,
    )
    request_confirmation = RequestConfirmationHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        resume_target_registry=resume_target_registry,
    )
    complete_answer_only = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        message_id_factory=id_factory,
    )
    complete_read_only_run = CompleteReadOnlyRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        message_id_factory=id_factory,
    )
    complete_write_run = CompleteWriteRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        message_id_factory=id_factory,
    )
    block_run = BlockRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        message_id_factory=id_factory,
    )
    publish_read_plan = PublishReadOnlyPlanHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    claim_read = ClaimReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    complete_read = CompleteReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        gateway=connector_reader,
    )
    finalize_read = FinalizeReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    fail_read = FailReadActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    publish_write_plan = PublishPlanHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    build_claim_context = BuildClaimContextHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        id_factory=id_factory,
        sign_claim_context=claim_context_signer or (lambda _payload: "test-signature"),
    )
    begin_execution_attempt = BeginExecutionAttemptHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    abort_claimed_execution = AbortClaimedExecutionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    expire_approval = ExpireApprovalHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    refresh_expired_action = RefreshExpiredActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        id_factory=id_factory,
        resume_target_registry=resume_target_registry,
        schedule_run_execution=None,
    )
    claim_execution = ClaimExecutionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        preflight_gateway=connector_reader,
        work_hours_provider=work_hours_provider,
        expire_approval=expire_approval,
        refresh_expired_action=refresh_expired_action,
        block_run=block_run,
    )
    require_recovery = RequireRecoveryHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        resume_target_registry=resume_target_registry,
    )
    begin_write_verification = BeginVerificationHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=now_ms,
        resume_target_registry=resume_target_registry,
    )
    record_review_result = RecordReviewResultHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
    )
    resolve_resource_ref = ResolveResourceRefHandler(unit_of_work_factory=unit_of_work_factory)
    return WorkflowApplicationServices(
        start_analysis=start_analysis,
        get_run_snapshot=get_run_snapshot,
        build_terminal_message=build_terminal_message,
        emit_terminal_trace=emit_terminal_trace,
        project_terminal_event=project_terminal_event,
        begin_retrieval=begin_retrieval,
        begin_planning=begin_planning,
        request_confirmation=request_confirmation,
        domain_validation=CanonicalDomainValidationService(
            tool_registry=tool_catalog,
            validate_action_arguments=ValidateActionArgumentsHandler(),
        ),
        complete_answer_only=complete_answer_only,
        complete_read_only_run=complete_read_only_run,
        complete_write_run=complete_write_run,
        block_run=block_run,
        publish_read_plan=publish_read_plan,
        claim_read=claim_read,
        complete_read=complete_read,
        finalize_read=finalize_read,
        fail_read=fail_read,
        publish_write_plan=publish_write_plan,
        build_claim_context=build_claim_context,
        begin_execution_attempt=begin_execution_attempt,
        abort_claimed_execution=abort_claimed_execution,
        classify_dispatch_result=ClassifyDispatchResultHandler(),
        expire_approval=expire_approval,
        refresh_expired_action=refresh_expired_action,
        claim_execution=claim_execution,
        store_write_success=StoreSuccessHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        mark_write_failed=MarkFailedHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        mark_write_unknown=MarkUnknownResultHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        verify_effect=VerifyEffectHandler(
            connector_read=connector_reader.connector_reader,
            tool_registry=tool_catalog,
            unit_of_work_factory=unit_of_work_factory,
            resolve_resource_ref=resolve_resource_ref,
        ),
        store_verification=StoreVerificationHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        require_recovery=require_recovery,
        resolve_recovery=ResolveRecoveryHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=now_ms,
            next_id=id_factory,
            resume_target_registry=resume_target_registry,
        ),
        require_write_reauth=RequireReauthHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=now_ms,
        ),
        lookup_unknown_result=LookupUnknownResultHandler(
            connector_read=connector_reader.connector_reader,
            tool_registry=tool_catalog,
            recovery_search_binding=google_workspace_internal_read_binding(
                "search_by_recovery_fingerprint"
            ),
            unit_of_work_factory=unit_of_work_factory,
        ),
        recover_existing_result=RecoverExistingResultHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        resolve_as_failed=ResolveAsFailedHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        begin_write_verification=begin_write_verification,
        resolve_resource_ref=resolve_resource_ref,
        cancel_pending_action=CancelPendingActionHandler(
            unit_of_work_factory=unit_of_work_factory, now_ms=now_ms
        ),
        finalize_cancel=FinalizeCancelHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=now_ms,
        ),
        continue_cancel_resolution=ContinueCancelResolutionHandler(
            unit_of_work_factory=unit_of_work_factory,
            settle_pending_action=lambda *args, **kwargs: runtime_hooks.call(
                "_settle_pending_cancel_action", *args, **kwargs
            ),
            reconcile_inflight_action=lambda *args, **kwargs: runtime_hooks.call(
                "_reconcile_cancelling_action", *args, **kwargs
            ),
            verify_executed_action=lambda *args, **kwargs: runtime_hooks.call(
                "_verify_cancelling_action", *args, **kwargs
            ),
            resolve_unknown_action=lambda *args, **kwargs: runtime_hooks.call(
                "_resolve_cancelling_unknown_action", *args, **kwargs
            ),
            finalize_cancel=None,
        ),
        record_review_result=record_review_result,
        validate_action_arguments=ValidateActionArgumentsHandler(),
    )


def _build_workflow_runtime(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    id_factory: Callable[[], str],
    checkpoint: SqliteCheckpointAdapter,
    retrieval_cache: RunRetrievalCachePort,
    materialize_admission_checkpoint: Callable[
        [WorkflowExecutionAdmissionV1, WorkflowHandoffV1], GraphCheckpointEnvelopeV1
    ],
    invoke_semantic_owner: Callable[[WorkflowExecutionAdmissionV1, WorkflowHandoffV1], None],
    resume_target_registry: ResumeTargetIssuer,
    lookup_unknown_result: LookupUnknownResultHandler,
    recover_existing_result: RecoverExistingResultHandler,
    resolve_as_failed: ResolveAsFailedHandler,
    require_recovery: RequireRecoveryHandler,
    materialize_recovery_snapshot: Callable[[str, dict[str, object], str], ResourceSnapshot],
    now_ms: Callable[[], int],
    reconciliation_interval_seconds: float = 1.0,
    reconciliation_batch_limit: int = 32,
) -> ProductionRuntime:
    """Bind the durable handoff slice exactly once at the service boundary."""
    workflow_execution = BackgroundRunExecutorAdapter(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        materialize_admission_checkpoint=materialize_admission_checkpoint,
        invoke_semantic_owner=invoke_semantic_owner,
        release_active_lineage=lambda run_id, thread_id, handoff_id, run_sequence: (
            checkpoint.release_active_lineage(
                run_id=run_id,
                thread_id=thread_id,
                handoff_id=handoff_id,
                run_sequence=run_sequence,
            )
        ),
    )
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=unit_of_work_factory,
        workflow_execution=workflow_execution,
        id_factory=id_factory,
        effective_binding_resolver=CheckpointEffectiveBindingResolver(
            checkpoint, resume_target_registry
        ),
    )
    reconcile_retrieval_cache_restart = ReconcileRetrievalCacheRestartHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint=checkpoint,
        retrieval_cache=retrieval_cache,
        resume_target_registry=resume_target_registry,
        schedule_run_execution=schedule,
        id_factory=id_factory,
    )
    reconcile_inflight = inflight_reconciliation.ReconcileInflightExecutionsHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        abort_claimed_execution=AbortClaimedExecutionHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        ),
        mark_unknown_result=MarkUnknownResultHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
        ),
        require_recovery=require_recovery,
        lookup_unknown_result=lookup_unknown_result,
        recover_existing_result=recover_existing_result,
        resolve_as_failed=resolve_as_failed,
        materialize_recovery_snapshot=materialize_recovery_snapshot,
        resume_target_registry=resume_target_registry,
        id_generator=_CallableUuidPort(id_factory),
    )
    redrive = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=unit_of_work_factory,
        schedule_run_execution=schedule,
        require_recovery=require_recovery,
        reconcile_retrieval_cache_restart=reconcile_retrieval_cache_restart,
        is_run_execution_active=workflow_execution.is_run_active,
    )
    loop = WorkflowHandoffReconciliationLoop(
        redrive=redrive,
        interval_seconds=reconciliation_interval_seconds,
        batch_limit=reconciliation_batch_limit,
    )
    return ProductionRuntime(
        checkpoint=checkpoint,
        reconcile_inflight_executions=reconcile_inflight,
        workflow_execution=workflow_execution,
        schedule_run_execution=schedule,
        redrive_workflow_handoffs=redrive,
        workflow_handoff_reconciliation_loop=loop,
    )


@dataclass(frozen=True, slots=True)
class _CallableUuidPort:
    factory: Callable[[], str]

    def new_uuid(self) -> str:
        return self.factory()


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class _VerifiedReleaseFile:
    file_path: str
    file_size: int
    sha256: str

    @classmethod
    def from_payload(cls, payload: object) -> _VerifiedReleaseFile:
        if not isinstance(payload, dict) or set(payload) != {
            "file_path",
            "file_size",
            "sha256",
        }:
            raise ValueError("verified release file schema is invalid")
        file_path = payload["file_path"]
        file_size = payload["file_size"]
        sha256 = payload["sha256"]
        path = PurePosixPath(file_path) if isinstance(file_path, str) else PurePosixPath()
        if (
            not isinstance(file_path, str)
            or not file_path
            or path.is_absolute()
            or path.as_posix() != file_path
            or ".." in path.parts
            or not isinstance(file_size, int)
            or isinstance(file_size, bool)
            or file_size < 0
            or not isinstance(sha256, str)
            or _SHA256_PATTERN.fullmatch(sha256) is None
        ):
            raise ValueError("verified release file value is invalid")
        return cls(file_path=file_path, file_size=file_size, sha256=sha256)

    def resolve_verified(self, install_root: Path) -> Path:
        candidate = (install_root / Path(*PurePosixPath(self.file_path).parts)).resolve()
        try:
            candidate.relative_to(install_root)
        except ValueError as error:
            raise CoreInitializationError("SIGNED_RUNTIME_PATH_INVALID") from error
        try:
            if not candidate.is_file() or candidate.stat().st_size != self.file_size:
                raise CoreInitializationError("RELEASE_ARTIFACT_TAMPERED")
        except OSError as error:
            raise CoreInitializationError("RELEASE_ARTIFACT_MISSING") from error
        try:
            actual_sha256 = calculate_file_sha256(candidate)
        except OSError as error:
            raise CoreInitializationError("RELEASE_ARTIFACT_MISSING") from error
        if actual_sha256 != self.sha256:
            raise CoreInitializationError("RELEASE_ARTIFACT_TAMPERED")
        return candidate


@dataclass(frozen=True, slots=True)
class ProductionRuntimeConfig:
    """Environment inputs supplied by a launcher without selecting dependencies."""

    runtime_root: Path
    working_directory: Path
    release_version: str
    build_channel: str
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"]
    oauth_environment: OAuthEnvironment
    oauth_client_id: str
    api_contract_version: str
    mcp_manifest_version: str
    policy_version: str
    database_migration_version: str
    configuration_source: Literal["SIGNED_RELEASE_MANIFEST", "EXPLICIT_DEVELOPMENT"]
    mcp_module_name: str | None = None
    keyring_store: SecretStorePort | None = None
    verified_release_files: tuple[_VerifiedReleaseFile, ...] = ()
    code_signature_verified_paths: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        values = (
            self.release_version,
            self.build_channel,
            self.oauth_client_id,
            self.api_contract_version,
            self.mcp_manifest_version,
            self.policy_version,
            self.database_migration_version,
        )
        if any(not value.strip() for value in values):
            raise ValueError("runtime configuration fields must be non-empty")
        if self.configuration_source == "SIGNED_RELEASE_MANIFEST":
            paths = [entry.file_path for entry in self.verified_release_files]
            if not paths or len(paths) != len(set(paths)):
                raise ValueError("signed runtime release file set is invalid")
            if not self.code_signature_verified_paths.issubset(paths):
                raise ValueError("signed runtime code signature proof is invalid")

    def verified_frontend_site(self) -> _VerifiedFrontendSite | None:
        """Project only release-indexed frontend assets before deferred core startup."""

        if self.configuration_source != "SIGNED_RELEASE_MANIFEST":
            return None
        return _build_verified_frontend_site(
            install_root=self.working_directory.resolve(),
            release_files={entry.file_path: entry for entry in self.verified_release_files},
        )

    @classmethod
    def development(
        cls,
        *,
        runtime_root: Path,
        working_directory: Path,
        mcp_manifest_version: str,
        mcp_module_name: str | None = None,
        keyring_store: SecretStorePort | None = None,
    ) -> ProductionRuntimeConfig:
        """Create the only explicit non-installed configuration mode."""

        return cls(
            runtime_root=runtime_root,
            working_directory=working_directory,
            release_version="0.1.0-dev",
            build_channel="DEVELOPMENT",
            deployment_profile="LOCAL_CAPABLE",
            oauth_environment=OAuthEnvironment.DEVELOPMENT,
            oauth_client_id="development-client-id",
            api_contract_version=API_CONTRACT_VERSION,
            mcp_manifest_version=mcp_manifest_version,
            policy_version="2026-08-06.p0",
            database_migration_version="development-latest",
            configuration_source="EXPLICIT_DEVELOPMENT",
            mcp_module_name=mcp_module_name,
            keyring_store=keyring_store,
        )

    @classmethod
    def from_signed_build_config(
        cls,
        payload: Mapping[str, object],
        *,
        runtime_root: Path,
        working_directory: Path,
        verified_release_files: object,
        code_signature_verified_paths: object,
    ) -> ProductionRuntimeConfig:
        """Project the closed Launcher handoff without ambient overrides."""

        if not runtime_root.is_absolute() or not working_directory.is_absolute():
            raise ValueError("signed runtime paths must be absolute")
        expected_fields = {
            "schema_version",
            "app_version",
            "build_channel",
            "deployment_profile",
            "oauth_env",
            "oauth_client_id",
            "api_contract_version",
            "mcp_schema_version",
            "policy_version",
            "database_migration_version",
        }
        if set(payload) != expected_fields or payload.get("schema_version") != 1:
            raise ValueError("signed build configuration schema is invalid")
        deployment_profile = payload.get("deployment_profile")
        if deployment_profile not in {"API_ONLY", "LOCAL_CAPABLE"}:
            raise ValueError("signed deployment profile is invalid")
        try:
            oauth_environment = OAuthEnvironment(str(payload.get("oauth_env")))
        except ValueError as error:
            raise ValueError("signed OAuth environment is invalid") from error

        def required_string(field: str) -> str:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"signed build configuration field is invalid: {field}")
            return value

        if not isinstance(verified_release_files, list):
            raise ValueError("verified release file set is invalid")
        release_files = tuple(
            _VerifiedReleaseFile.from_payload(entry) for entry in verified_release_files
        )
        if not isinstance(code_signature_verified_paths, list) or not all(
            isinstance(path, str) for path in code_signature_verified_paths
        ):
            raise ValueError("code signature proof is invalid")

        return cls(
            runtime_root=runtime_root,
            working_directory=working_directory,
            release_version=required_string("app_version"),
            build_channel=required_string("build_channel"),
            deployment_profile=cast(Literal["API_ONLY", "LOCAL_CAPABLE"], deployment_profile),
            oauth_environment=oauth_environment,
            oauth_client_id=required_string("oauth_client_id"),
            api_contract_version=required_string("api_contract_version"),
            mcp_manifest_version=required_string("mcp_schema_version"),
            policy_version=required_string("policy_version"),
            database_migration_version=required_string("database_migration_version"),
            configuration_source="SIGNED_RELEASE_MANIFEST",
            verified_release_files=release_files,
            code_signature_verified_paths=frozenset(code_signature_verified_paths),
        )


def drain_workflow_handoffs_to_quiescence(
    redrive: RedriveWorkflowHandoffsHandler,
    *,
    batch_limit: int = 32,
    max_passes: int = 1000,
) -> int:
    """Repeatedly invoke bounded redrive passes before the live reconciliation
    loop starts / READY is published, stopping only once a pass proves
    ``has_more=false`` -- it saw strictly fewer than ``batch_limit`` actionable
    rows, so every remaining actionable row was inspected this pass. Startup
    and the live ``WorkflowHandoffReconciliationLoop`` both drive this same
    ``RedriveWorkflowHandoffsHandler`` -- there is exactly one reconciliation
    authority. ``max_passes`` is a hard circuit breaker: it guarantees this
    never spins forever even if actionable rows are permanently stuck (e.g.
    fail-closed BLOCKED_BINDING handoffs), raising instead of hanging.
    Returns the number of passes executed.
    """
    if batch_limit < 1:
        raise ValueError("batch_limit must be positive")
    for pass_index in range(1, max_passes + 1):
        result = redrive(RedriveWorkflowHandoffsCommand(limit=batch_limit))
        if not result.has_more:
            return pass_index
    raise RuntimeError(
        f"workflow handoff startup drain did not reach quiescence within {max_passes} passes"
    )


GOOGLE_WORKSPACE_MCP_MODULE = (
    "google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint"
)


@dataclass(frozen=True, slots=True)
class DevelopmentConnectorBundle:
    runtime_registry: ConnectorRuntimeRegistry
    tool_registry: SignedToolRegistry
    installed_manifest: InstalledConnectorManifestV1
    google_connector: GoogleWorkspaceConnector


@dataclass(frozen=True, slots=True)
class _LauncherVerifiedArtifactSignatureVerifier:
    install_root: Path
    release_files: Mapping[str, _VerifiedReleaseFile]
    verified_paths: frozenset[str]

    def verify(
        self,
        *,
        executable_path: str,
        expected_binary_sha256: str,
    ) -> ArtifactSignatureDecision:
        try:
            relative = Path(executable_path).resolve().relative_to(self.install_root).as_posix()
        except ValueError:
            return ArtifactSignatureDecision(False, "artifact escaped install root")
        release_file = self.release_files.get(relative)
        allowed = (
            relative in self.verified_paths
            and release_file is not None
            and release_file.sha256 == expected_binary_sha256
        )
        return ArtifactSignatureDecision(allowed, None if allowed else "signature proof missing")


@dataclass(frozen=True, slots=True)
class _VerifiedFrontendSite:
    root: Path
    allowed_files: Mapping[str, _VerifiedReleaseFile]

    @property
    def index_path(self) -> Path:
        index = self.resolve_asset("")
        if index is None:
            raise CoreInitializationError("FRONTEND_ARTIFACT_TAMPERED")
        return index

    def resolve_asset(self, path: str) -> Path | None:
        requested = path if path else "index.html"
        relative = PurePosixPath(requested)
        if relative.is_absolute() or relative.as_posix() != requested or ".." in relative.parts:
            return None
        binding = self.allowed_files.get(f"frontend/{requested}")
        if binding is None:
            return None
        try:
            return binding.resolve_verified(self.root.parent)
        except CoreInitializationError:
            return None


def _google_oauth_scopes(registry: SignedToolRegistry) -> tuple[str, ...]:
    scopes = {
        "openid",
        "userinfo.email",
    }
    for entry in registry.entries:
        if entry.connector_id != GOOGLE_WORKSPACE_CONNECTOR_ID:
            continue
        scopes.update(entry.required_scopes)
    return tuple(sorted(scopes))


def _required_release_file(
    release_files: Mapping[str, _VerifiedReleaseFile], relative: str
) -> _VerifiedReleaseFile:
    try:
        return release_files[relative]
    except KeyError as error:
        raise CoreInitializationError("RELEASE_ARTIFACT_MISSING") from error


def _verify_installed_runtime_path(
    path: Path,
    *,
    install_root: Path,
    release_files: Mapping[str, _VerifiedReleaseFile],
) -> None:
    try:
        relative = path.resolve().relative_to(install_root).as_posix()
    except ValueError as error:
        raise CoreInitializationError("SIGNED_RUNTIME_PATH_INVALID") from error
    _required_release_file(release_files, relative).resolve_verified(install_root)


def _load_installed_llm_runtime_selection(
    *,
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"],
    release_version: str,
    install_root: Path,
    release_files: Mapping[str, _VerifiedReleaseFile],
) -> LlmRuntimeSelectionV1:
    manifest_relative = "manifests/model-manifest-v1.json"
    decision_relative = "manifests/local-model-product-decision-v1.json"
    if deployment_profile == "API_ONLY":
        if manifest_relative in release_files or decision_relative in release_files:
            raise CoreInitializationError("API_ONLY_LOCAL_RELEASE_ARTIFACT_FORBIDDEN")
        return LlmRuntimeSelectionV1(
            schema_version=1,
            deployment_profile="API_ONLY",
            selected_model=None,
            ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
            model_manifest_hash=None,
            product_decision_hash=None,
            local_runtime_activation_status=(
                LocalRuntimeActivationStatus.DISABLED_BY_DEPLOYMENT_PROFILE
            ),
            requirements=None,
            release_version=release_version,
        )
    try:
        manifest_binding = release_files[manifest_relative]
    except KeyError as error:
        raise CoreInitializationError("MODEL_MANIFEST_MISSING") from error
    try:
        decision_binding = release_files[decision_relative]
    except KeyError as error:
        raise CoreInitializationError("PRODUCT_DECISION_MISSING") from error
    manifest_path = manifest_binding.resolve_verified(install_root)
    decision_path = decision_binding.resolve_verified(install_root)
    try:
        manifest = ModelManifestV1.from_bytes(manifest_path.read_bytes())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise CoreInitializationError("MODEL_MANIFEST_INVALID") from error
    try:
        decision = LocalModelProductDecisionV1.from_bytes(decision_path.read_bytes())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise CoreInitializationError("PRODUCT_DECISION_INVALID") from error
    manifest_hash = sha256(manifest.to_canonical_bytes()).hexdigest()
    if decision.model_manifest_hash != manifest_hash:
        raise CoreInitializationError("PRODUCT_DECISION_MANIFEST_MISMATCH")
    if decision.release_version != release_version:
        raise CoreInitializationError("PRODUCT_DECISION_STALE")
    selected = next(
        (
            entry
            for entry in manifest.approved_models
            if entry.model_id == decision.selected_model_id
        ),
        None,
    )
    if selected is None:
        raise CoreInitializationError("PRODUCT_DECISION_MODEL_NOT_APPROVED")
    return LlmRuntimeSelectionV1(
        schema_version=1,
        deployment_profile="LOCAL_CAPABLE",
        selected_model=ApprovedModelInfo(
            model_id=selected.model_id,
            runtime="OLLAMA",
            manifest_version="1",
            schema_version="1",
            minimum_runtime_version=manifest.minimum_ollama_version,
            digest=selected.model_hash,
        ),
        ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
        model_manifest_hash=manifest_hash,
        product_decision_hash=decision_binding.sha256,
        local_runtime_activation_status=LocalRuntimeActivationStatus.ACTIVE,
        requirements=LocalRuntimeRequirementsV1(
            minimum_cpu_logical_cores=decision.minimum_cpu_logical_cores,
            minimum_ram_bytes=decision.minimum_ram_bytes,
            minimum_vram_bytes=decision.minimum_vram_bytes,
            supported_os=decision.supported_os,
            supported_architecture=decision.supported_architecture,
        ),
        release_version=release_version,
    )


def _build_verified_frontend_site(
    *,
    install_root: Path,
    release_files: Mapping[str, _VerifiedReleaseFile],
) -> _VerifiedFrontendSite:
    _required_release_file(release_files, "frontend/index.html").resolve_verified(install_root)
    return _VerifiedFrontendSite(
        root=install_root / "frontend",
        allowed_files=dict(release_files),
    )


def _build_connectors(
    *,
    mcp_manifest_path: Path,
    mcp_manifest_version: str,
    service_instance_id: str,
    attachment_staging_dir: Path,
    python_executable: Path,
    working_directory: Path,
    environment: str,
    oauth_client_id: str,
    mcp_module_name: str = GOOGLE_WORKSPACE_MCP_MODULE,
    configuration_source: Literal[
        "SIGNED_RELEASE_MANIFEST", "EXPLICIT_DEVELOPMENT"
    ] = "EXPLICIT_DEVELOPMENT",
    verified_release_files: tuple[_VerifiedReleaseFile, ...] = (),
    code_signature_verified_paths: frozenset[str] = frozenset(),
) -> DevelopmentConnectorBundle:
    signature_verifier = None
    if configuration_source == "SIGNED_RELEASE_MANIFEST":
        release_files = {entry.file_path: entry for entry in verified_release_files}
        installed_binding = _required_release_file(
            release_files, "manifests/installed-connectors-v1.json"
        )
        registry_binding = _required_release_file(
            release_files, "manifests/signed-tool-registry-v1.json"
        )
        installed_path = installed_binding.resolve_verified(working_directory)
        registry_path = registry_binding.resolve_verified(working_directory)
        installed_manifest = load_installed_connector_manifest(
            installed_path,
            expected_sha256=installed_binding.sha256,
        )
        tool_registry = load_signed_tool_registry(
            registry_path,
            expected_sha256=registry_binding.sha256,
        )
        signature_verifier = _LauncherVerifiedArtifactSignatureVerifier(
            install_root=working_directory,
            release_files=release_files,
            verified_paths=code_signature_verified_paths,
        )
    else:
        release_files = {}
        tool_registry = load_signed_tool_registry()
        installed_manifest = load_installed_connector_manifest()
    installed_connector = installed_manifest.get_required(GOOGLE_WORKSPACE_CONNECTOR_ID)
    if (
        installed_connector.provider_namespace != "google"
        or installed_connector.connector_package != "workspace"
        or not installed_connector.tool_projection_path.endswith(
            "/google_workspace/tool-descriptor-projection-v1.json"
        )
    ):
        raise ValueError("installed Google Workspace connector binding is invalid")
    if configuration_source == "SIGNED_RELEASE_MANIFEST":
        if installed_connector.mcp_schema_version != mcp_manifest_version:
            raise CoreInitializationError("MCP_SCHEMA_MISMATCH")
        executable_binding = _required_release_file(
            release_files, installed_connector.executable_path
        )
        projection_binding = _required_release_file(
            release_files, installed_connector.tool_projection_path
        )
        executable_path = executable_binding.resolve_verified(working_directory)
        mcp_manifest_path = projection_binding.resolve_verified(working_directory)
        expected_binary_sha256 = executable_binding.sha256
        expected_manifest_sha256 = projection_binding.sha256
        module_name = None
        connector_working_directory = executable_path.parent
    else:
        executable_path = python_executable
        expected_binary_sha256 = calculate_file_sha256(python_executable)
        expected_manifest_sha256 = calculate_file_sha256(mcp_manifest_path)
        module_name = mcp_module_name
        connector_working_directory = working_directory
    runtime_registry = ConnectorRuntimeRegistry()
    descriptor = build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(executable_path),
            manifest_path=str(mcp_manifest_path),
            expected_binary_sha256=expected_binary_sha256,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_manifest_version=mcp_manifest_version,
            expected_protocol_version=mcp_manifest_version,
            expected_registry_manifest_hash=tool_registry.entries_hash,
            startup_timeout_ms=5_000,
            request_timeout_ms=30_000,
            max_restart_count=1,
            environment=environment,
            service_instance_id=service_instance_id,
            module_name=module_name,
            working_directory=str(connector_working_directory),
            extra_environment={
                ATTACHMENT_STAGING_DIR_ENV: str(attachment_staging_dir),
                "GOOGLE_OAUTH_ENV": environment,
                "GOOGLE_OAUTH_CLIENT_ID": oauth_client_id,
            },
        ),
        expected_tool_descriptors=tuple(
            tool_registry.descriptor_expectations(GOOGLE_WORKSPACE_CONNECTOR_ID)
        ),
    )
    google_connector = GoogleWorkspaceConnector(
        descriptor=descriptor,
        runtime_registry=runtime_registry,
        signature_verifier=signature_verifier,
    )
    google_connector.start()
    return DevelopmentConnectorBundle(
        runtime_registry=runtime_registry,
        tool_registry=tool_registry,
        installed_manifest=installed_manifest,
        google_connector=google_connector,
    )


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HISTORY_MESSAGE_LIMIT = 200
HISTORY_RUN_LIMIT = 200
RELEASE_VERSION = "0.1.0-dev"


@dataclass(frozen=True, slots=True)
class ServiceInstanceLauncherProbeVerifier:
    """Bind readiness to the exact service identity supplied by Launcher."""

    service_instance_id: str

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        return LauncherProbeDecision(allowed=service_instance_id == self.service_instance_id)


class CoreInitializationError(RuntimeError):
    """Redacted core-startup failure exposed through readiness only."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class SafeModeRecoveryBindings:
    """Bounded operational handlers available while the Product core is offline."""

    list_backups_handler: ListBackupsHandler
    create_backup_handler: CreateBackupHandler
    restore_backup_handler: RestoreBackupHandler
    request_shutdown_handler: RequestShutdownHandler


class _BootReadinessAggregator(ReadinessAggregator):
    """Expose initialization state without making liveness depend on core startup."""

    def __init__(self, safe_mode: SafeModeController) -> None:
        self._safe_mode = safe_mode
        self._delegate: ReadinessAggregator | None = None
        self._failure_code: str | None = None

    def bind(self, delegate: ReadinessAggregator) -> None:
        self._delegate = delegate
        self._failure_code = None

    def fail(self, code: str) -> None:
        self._failure_code = code

    def evaluate(self) -> ReadinessReport:
        if self._failure_code is not None:
            return ReadinessReport(
                state=ReadinessState.SAFE_MODE,
                checks=(
                    ReadinessCheckResult(
                        name="core_initialization",
                        state=ReadinessState.SAFE_MODE,
                        detail=self._failure_code,
                    ),
                ),
            )
        if self._delegate is None:
            return ReadinessReport(
                state=ReadinessState.NOT_READY,
                checks=(
                    ReadinessCheckResult(
                        name="core_initialization",
                        state=ReadinessState.NOT_READY,
                        detail="INITIALIZING",
                    ),
                ),
            )
        return self._delegate.evaluate()


class DeferredApiContainer:
    """Stable delivery shell while the single production runtime is assembled."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        service_instance_id: str,
        bootstrap_secret: str,
        release_version: str = RELEASE_VERSION,
        environment: str = "DEVELOPMENT",
        api_contract_version: str = API_CONTRACT_VERSION,
        deployment_profile: str = "LOCAL_CAPABLE",
        frontend_site: Any | None = None,
        core_builder: Callable[..., ApiContainer],
        recovery_builder: Callable[[Callable[[], bool]], SafeModeRecoveryBindings] | None = None,
    ) -> None:
        self._core: ApiContainer | None = None
        self._core_builder = core_builder
        self._recovery_builder = recovery_builder
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self.safe_mode_controller = SafeModeController()
        self.core_initialization_in_progress = True
        self.readiness_aggregator = _BootReadinessAggregator(self.safe_mode_controller)
        self.current_account_id_provider: Callable[[], str | None] = lambda: None
        self.create_conversation_handler: Any = None
        self.list_conversations_handler: Any = None
        self.get_conversation_history_handler: Any = None
        self.clock = SystemClockAdapter()
        self.id_generator = Uuid4Adapter()
        self.release_version = release_version
        self.environment = environment
        self.service_instance_id = service_instance_id
        self.api_contract_version = api_contract_version
        self.local_bind_host = host
        self.local_bind_port = port
        self.max_request_body_bytes = 64 * 1024
        self.max_attachment_bytes = MAX_STAGED_FILE_BYTES
        self.api_docs_enabled = False
        self.frontend_site = frontend_site
        self.additional_readiness_checks: tuple[Any, ...] = ()
        self.shutdown_callbacks = (self.close,)
        self.startup_callbacks = (self._initialize,)
        self.client_address_resolver: Callable[[Any], str | None] | None = None
        self.operational_log_sink = None
        startup_runtime_mode = ProcessRuntimeModeAdapter("AUTO")
        startup_circuits = ProcessComponentCircuitStateAdapter()
        self.get_runtime_status_handler = GetRuntimeStatusHandler(
            runtime_mode=startup_runtime_mode,
            oauth=cast(OAuthCredentialPort, _UnavailableStartupOAuthStatus()),
            llm_status=cast(LlmRuntimeStatusPort, _UnavailableStartupLlmStatus()),
            circuits=startup_circuits,
            service_instance_id=service_instance_id,
            release_version=release_version,
            api_contract_version=api_contract_version,
            deployment_profile=deployment_profile,
            recovery_required=lambda: self.safe_mode_controller.snapshot().enabled,
            database_status=lambda: "UNAVAILABLE",
            migration_status=self._startup_migration_status,
            sse_status=lambda: "UNAVAILABLE",
            recent_sanitized_error_code=self._startup_error_code,
            launcher_status=lambda: "DEGRADED",
            manifest_status=lambda: "UNAVAILABLE",
            safe_mode=lambda: self.safe_mode_controller.snapshot().enabled,
        )
        self.update_runtime_mode_handler = None
        self.get_settings_handler = None
        self.update_settings_handler = None
        self.list_backups_handler: Any = None
        self.create_backup_handler: Any = None
        self.restore_backup_handler: Any = None
        self.request_shutdown_handler: Any = None
        self._bootstrap_secret = bootstrap_secret
        self._bootstrap_grant_store = InMemoryBootstrapGrantStore()
        self._session_manager = InMemoryLocalSessionManager()
        self._bootstrap_grant_store.provision(
            secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            now_ms=self.clock.now_ms(),
        )
        self.api_access_guard = LocalApiAccessGuard(
            expected_host=f"{host}:{port}",
            expected_origin=f"http://{host}:{port}",
            service_instance_id=service_instance_id,
            session_manager=self._session_manager,
            release_version=release_version,
            environment=environment,
            now_ms=self.clock.now_ms,
        )
        self.launcher_probe_verifier = ServiceInstanceLauncherProbeVerifier(service_instance_id)
        self.bootstrap_grant_store = self._bootstrap_grant_store
        self.local_session_manager = self._session_manager

    def _startup_error_code(self) -> str | None:
        reasons = self.safe_mode_controller.snapshot().reason_codes
        return reasons[0] if reasons else None

    def _startup_migration_status(self) -> Literal["READY", "PENDING", "FAILED"]:
        return (
            "FAILED"
            if "MIGRATION_FAILED" in self.safe_mode_controller.snapshot().reason_codes
            else "PENDING"
        )

    async def _initialize(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._core_builder,
                host=self.local_bind_host,
                port=self.local_bind_port,
                bootstrap_secret=self._bootstrap_secret,
                service_instance_id=self.service_instance_id,
                safe_mode_controller=self.safe_mode_controller,
            )
        )
        try:
            core = await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._closed = True
            core = await worker
            _close_container(core)
            raise
        except CoreInitializationError as error:
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable(error.safe_code)
            self.readiness_aggregator.fail(error.safe_code)
            self._bind_safe_mode_recovery()
            return
        except Exception:
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable("CORE_INITIALIZATION_FAILED")
            self.readiness_aggregator.fail("CORE_INITIALIZATION_FAILED")
            self._bind_safe_mode_recovery()
            return
        if self._closed:
            _close_container(core)
            return
        try:
            for callback in core.startup_callbacks:
                await callback()
        except Exception:
            _close_container(core)
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable("CORE_STARTUP_RECONCILIATION_FAILED")
            self.readiness_aggregator.fail("CORE_STARTUP_RECONCILIATION_FAILED")
            self._bind_safe_mode_recovery()
            return
        self._core = core
        self.readiness_aggregator.bind(core.readiness_aggregator)
        self.current_account_id_provider = core.current_account_id_provider
        self.core_initialization_in_progress = False
        self.safe_mode_controller.disable()

    def _bind_safe_mode_recovery(self) -> None:
        if self._recovery_builder is None:
            return
        bindings = self._recovery_builder(self._retry_core_after_restore)
        self.list_backups_handler = bindings.list_backups_handler
        self.create_backup_handler = bindings.create_backup_handler
        self.restore_backup_handler = bindings.restore_backup_handler
        self.request_shutdown_handler = bindings.request_shutdown_handler

    def _retry_core_after_restore(self) -> bool:
        if self._event_loop is None or self._closed:
            return False
        future = asyncio.run_coroutine_threadsafe(
            self._recover_core_after_restore(), self._event_loop
        )
        try:
            return future.result(timeout=60)
        except Exception:
            return False

    async def _recover_core_after_restore(self) -> bool:
        self.core_initialization_in_progress = True
        previous_reasons = self.safe_mode_controller.snapshot().reason_codes
        self.safe_mode_controller.disable()
        core: ApiContainer | None = None
        try:
            core = await asyncio.to_thread(
                self._core_builder,
                host=self.local_bind_host,
                port=self.local_bind_port,
                bootstrap_secret=self._bootstrap_secret,
                service_instance_id=self.service_instance_id,
                safe_mode_controller=self.safe_mode_controller,
            )
            for callback in core.startup_callbacks:
                await callback()
            if core.readiness_aggregator.evaluate().state is not ReadinessState.READY:
                _close_container(core)
                self.core_initialization_in_progress = False
                self.safe_mode_controller.enable(*previous_reasons)
                return False
        except Exception:
            if core is not None:
                _close_container(core)
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable(*previous_reasons)
            return False
        assert core is not None
        self._core = core
        self.readiness_aggregator.bind(core.readiness_aggregator)
        self.current_account_id_provider = core.current_account_id_provider
        self.core_initialization_in_progress = False
        self.safe_mode_controller.disable()
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._core is not None:
            _close_container(self._core)

    def __getattr__(self, name: str) -> Any:
        if self._core is not None:
            return getattr(self._core, name)
        raise RuntimeError("core initialization is incomplete")


def _close_container(container: ApiContainer) -> None:
    for callback in container.shutdown_callbacks:
        callback()


class _UnavailableStartupOAuthStatus:
    """Read-only connector facts available before the production core is bound."""

    def get_connection_status(self, connector_id: str) -> OAuthConnectionMetadata:
        return OAuthConnectionMetadata(
            schema_version=1,
            connector_id=connector_id,
            account_id=None,
            display_email=None,
            connection_status="UNAVAILABLE",
            granted_scopes=(),
            missing_required_scopes=(),
        )


class _UnavailableStartupLlmStatus:
    """Read-only LLM facts available before the production core is bound."""

    def get_status(self, provider: str) -> LlmProviderRuntimeStatus:
        return LlmProviderRuntimeStatus(
            schema_version=1,
            provider=provider,
            configured=False,
            availability="UNAVAILABLE",
            model_id=None,
            error_code="CORE_INITIALIZATION_INCOMPLETE",
        )


@dataclass(slots=True)
class _ShutdownComponent:
    stop_commands: Callable[[], None] = lambda: None
    stop_coordinator: Callable[[], None] = lambda: None
    await_coordinator: Callable[[float], None] = lambda _timeout: None
    flush_runtime: Callable[[], None] = lambda: None
    flush_observability: Callable[[], None] = lambda: None
    checkpoint_persistence: Callable[[], None] = lambda: None
    close_component: Callable[[], None] = lambda: None
    invalidate_sessions: Callable[[], None] = lambda: None

    def stop_accepting_commands(self) -> None:
        self.stop_commands()

    def stop_accepting(self) -> None:
        self.stop_coordinator()

    def shutdown(self, timeout_seconds: float) -> None:
        self.await_coordinator(timeout_seconds)

    def flush_or_checkpoint(self) -> None:
        self.flush_runtime()

    def flush(self) -> None:
        self.flush_observability()

    def checkpoint_wal(self) -> None:
        self.checkpoint_persistence()

    def close(self) -> None:
        self.close_component()

    def invalidate_all(self) -> None:
        self.invalidate_sessions()


def build_safe_mode_recovery_bindings(
    *,
    runtime_root: Path,
    release_version: str,
    retry_core_after_restore: Callable[[], bool],
    request_process_exit: Callable[[], None],
) -> SafeModeRecoveryBindings:
    """Compose restore/shutdown only after normal core startup has failed."""

    root = runtime_root.resolve()
    clock = SystemClockAdapter()
    replay = FilesystemOperationalCommandReplayAdapter(root / "operational-command-replay")
    migration_version = f"{discover_migrations()[-1].version:04d}"
    maintenance_gate = ProcessMaintenanceGateAdapter(has_active_write=lambda: False)
    backups = FilesystemBackupAdapter(
        database_path=root / "data" / "google_work_agent.db",
        backups_dir=root / "backups",
        clock=clock,
        maintenance_gate=maintenance_gate,
        release_version=release_version,
        domain_contract_version="1",
        schema_version=migration_version,
        supported_restore_schema_versions=("0018", migration_version),
        post_restore_readiness=retry_core_after_restore,
    )
    shutdown = ProcessShutdownAdapter(
        command_gate=_ShutdownComponent(),
        coordinator=_ShutdownComponent(),
        workflow_runtime=_ShutdownComponent(),
        observability=_ShutdownComponent(),
        persistence=_ShutdownComponent(),
        mcp_transport=_ShutdownComponent(),
        sessions=_ShutdownComponent(),
        clock=clock,
        marker_path=root / "shutdown" / "request.json",
        request_process_exit=request_process_exit,
    )
    return SafeModeRecoveryBindings(
        list_backups_handler=ListBackupsHandler(backups),
        create_backup_handler=CreateBackupHandler(backups=backups, replay=replay),
        restore_backup_handler=RestoreBackupHandler(backups=backups, replay=replay),
        request_shutdown_handler=RequestShutdownHandler(shutdown=shutdown, replay=replay),
    )


class _PromptInactiveWorkflowRuntime:
    """Safe placeholder: workflows cannot execute until prompts are approved."""

    def close(self) -> None:
        return None

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        return self._not_available(request.run_id, request.workflow_key)

    def resolve_pending_confirmation(self, _run_id: str) -> dict[str, object] | None:
        return None

    @staticmethod
    def _not_available(run_id: str, workflow_key: str) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=WorkflowOutcome.FAILED,
            payload={"safe_error_code": "PROMPT_NOT_ACTIVE"},
        )


def build_production_runtime(
    *,
    runtime_root: Path,
    working_directory: Path,
    mcp_manifest_version: str,
    bootstrap_secret: str,
    release_version: str,
    build_channel: str,
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"],
    oauth_environment: OAuthEnvironment,
    oauth_client_id: str,
    api_contract_version: str,
    policy_version: str,
    database_migration_version: str,
    configuration_source: Literal["SIGNED_RELEASE_MANIFEST", "EXPLICIT_DEVELOPMENT"],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    service_instance_id: str | None = None,
    safe_mode_controller: SafeModeController | None = None,
    mcp_module_name: str | None = None,
    keyring_store: SecretStorePort | None = None,
    verified_release_files: tuple[_VerifiedReleaseFile, ...] = (),
    code_signature_verified_paths: frozenset[str] = frozenset(),
    request_process_exit: Callable[[], None] | None = None,
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
) -> ApiContainer:
    """Assemble the local service from authenticated or explicit development inputs."""

    LocalBindPolicy(host=host, port=port).validate()
    if configuration_source == "SIGNED_RELEASE_MANIFEST":
        if service_instance_id is None:
            raise CoreInitializationError("SERVICE_INSTANCE_ID_REQUIRED")
        if not runtime_root.is_absolute() or not working_directory.is_absolute():
            raise CoreInitializationError("SIGNED_RUNTIME_PATH_INVALID")
    safe_mode = safe_mode_controller or SafeModeController()
    approval_policy_config = ApprovalPolicyConfigV1(approval_ttl_minutes=30)
    root = runtime_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    install_root = working_directory.resolve()
    release_files = {entry.file_path: entry for entry in verified_release_files}
    database_path = root / "data" / "google_work_agent.db"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    mcp_manifest_path = (
        root / "mcp-manifest.json"
        if configuration_source == "SIGNED_RELEASE_MANIFEST"
        else _write_mcp_manifest(root)
    )
    prompt_manifest_path = default_prompt_manifest_path()
    frontend_site = None
    runtime_selection = LlmRuntimeSelectionV1(
        schema_version=1,
        deployment_profile=deployment_profile,
        selected_model=None,
        ollama_endpoint_policy="FIXED_LOOPBACK_OLLAMA_V1",
        model_manifest_hash=None,
        product_decision_hash=None,
        local_runtime_activation_status=(
            LocalRuntimeActivationStatus.DISABLED_BY_DEPLOYMENT_PROFILE
            if deployment_profile == "API_ONLY"
            else LocalRuntimeActivationStatus.DEFERRED_UNTIL_PRODUCT_DECISION
        ),
        requirements=None,
        release_version=release_version,
    )
    if configuration_source == "SIGNED_RELEASE_MANIFEST":
        _verify_installed_runtime_path(
            prompt_manifest_path,
            install_root=install_root,
            release_files=release_files,
        )
        frontend_site = _build_verified_frontend_site(
            install_root=install_root,
            release_files=release_files,
        )
        runtime_selection = _load_installed_llm_runtime_selection(
            deployment_profile=deployment_profile,
            release_version=release_version,
            install_root=install_root,
            release_files=release_files,
        )
    clock = SystemClockAdapter()
    id_generator = Uuid4Adapter()
    service_instance_id = service_instance_id or f"dev-{uuid.uuid4()}"
    attachment_staging_dir = root / "cache" / "attachments"
    attachment_staging = FilesystemAttachmentStagingAdapter(
        staging_dir=attachment_staging_dir,
        now_ms=clock.now_ms,
    )
    attachment_staging.cleanup_expired()
    operational_replay = FilesystemOperationalCommandReplayAdapter(
        root / "operational-command-replay"
    )
    actual_database_migration_version = "0000"
    try:
        with connect_sqlite(database_path) as connection:
            migration_results = apply_migrations(connection, now_ms=clock.now_ms)
        actual_database_migration_version = (
            f"{migration_results[-1].version:04d}" if migration_results else "0000"
        )
        if (
            configuration_source == "SIGNED_RELEASE_MANIFEST"
            and database_migration_version != actual_database_migration_version
        ):
            raise CoreInitializationError("MIGRATION_VERSION_MISMATCH")
    except (sqlite3.Error, MigrationError) as error:
        raise CoreInitializationError("MIGRATION_FAILED") from error

    try:
        resume_target_registry = ResumeTargetRegistry(
            node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
            graph_version=RESUME_CONTRACT_VERSION,
        )
        checkpoint = SqliteCheckpointAdapter(
            database_path,
            now_ms=clock.now_ms,
            target_resolver=NativeCheckpointTargetResolver(resume_target_registry),
        )
        checkpoint_control = LangGraphCheckpointControlAdapter(
            checkpoint_port=checkpoint,
            native_saver=checkpoint,
        )
    except Exception as error:
        raise CoreInitializationError("CHECKPOINT_INITIALIZATION_FAILED") from error
    try:
        active_keyring_store = keyring_store or OsKeyringSecretStoreAdapter(
            service_name=keyring_service_name(
                environment=oauth_environment.value,
                credential_type="llm-api-key",
            )
        )
    except RuntimeError as error:
        raise CoreInitializationError("KEYRING_UNAVAILABLE") from error

    try:
        connector_bundle = _build_connectors(
            mcp_manifest_path=mcp_manifest_path,
            mcp_manifest_version=mcp_manifest_version,
            service_instance_id=service_instance_id,
            attachment_staging_dir=attachment_staging_dir,
            python_executable=Path(sys.executable).resolve(),
            working_directory=working_directory.resolve(),
            environment=oauth_environment.value,
            oauth_client_id=oauth_client_id,
            configuration_source=configuration_source,
            verified_release_files=verified_release_files,
            code_signature_verified_paths=code_signature_verified_paths,
            **({} if mcp_module_name is None else {"mcp_module_name": mcp_module_name}),
        )
    except CoreInitializationError:
        raise
    except MCPClientPortError as error:
        raise CoreInitializationError("MCP_HANDSHAKE_FAILED") from error
    except (LookupError, OSError, ValueError) as error:
        raise CoreInitializationError("MCP_MANIFEST_INVALID") from error
    connector_registry = connector_bundle.runtime_registry
    mcp_manifest_path = Path(
        connector_bundle.google_connector.descriptor.artifact_config.manifest_path
    )
    mcp_executable_path = Path(
        connector_bundle.google_connector.descriptor.artifact_config.executable_path
    )
    if connector_bundle.tool_registry.contract_version != policy_version:
        connector_registry.close_all()
        raise CoreInitializationError("POLICY_VERSION_MISMATCH")
    google_connector = connector_bundle.google_connector
    google_provider = google_connector.oauth_port
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    read_unit_of_work_factory = sqlite_read_unit_of_work_factory(database_path)
    connected_account_store_factory = sqlite_connected_account_store_factory(database_path)
    get_connection_status = GetConnectionStatusHandler(
        google_provider,
        connected_account_store_factory=connected_account_store_factory,
        now_ms=clock.now_ms,
    )

    def current_account_id() -> str | None:
        return get_connection_status(
            GetConnectionStatusQuery(connector_id="google_workspace")
        ).connection.account_id

    try:
        llm_runtime, settings_service, credential_service, llm_status_service = _build_llm_runtime(
            settings_path=root / "settings" / "app-settings.json",
            prompt_manifest_path=prompt_manifest_path,
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
            keyring_store=active_keyring_store,
            environment=oauth_environment.value,
            release_version=release_version,
            runtime_selection=runtime_selection,
        )
    except RuntimeError as error:
        connector_registry.close_all()
        raise CoreInitializationError("LLM_RUNTIME_INITIALIZATION_FAILED") from error
    runtime_mode = ProcessRuntimeModeAdapter(
        initial_mode=cast(Any, settings_service.get_settings().preferred_llm_mode)
    )
    component_circuits = ProcessComponentCircuitStateAdapter(
        failure_threshold=settings_service.get_settings().circuit_failure_threshold,
        open_duration_ms=settings_service.get_settings().circuit_open_duration_ms,
    )
    check_component_circuit = CheckComponentCircuitHandler(component_circuits)
    record_component_call_result = RecordComponentCallResultHandler(component_circuits)
    diagnostics_adapter = FilesystemDiagnosticsAdapter(
        collect_snapshot=lambda: {
            "release_version": release_version,
            "build_channel": build_channel,
            "environment": oauth_environment.value,
            "policy_version": policy_version,
            "service_instance_id": service_instance_id,
        },
        diagnostics_dir=root / "diagnostics",
        now_ms=clock.now_ms,
        max_bundle_bytes=256 * 1024,
    )
    prompt_active = True
    workflow_runtime: Any
    connector_reader = CircuitProtectedConnectorReadPort(
        delegate=google_connector.read_port,
        connector_id="google-workspace",
        check=check_component_circuit,
        record=record_component_call_result,
        now_ms=clock.now_ms,
    )
    connector_writer = CircuitProtectedConnectorWritePort(
        delegate=google_connector.write_port,
        connector_id="google-workspace",
        check=check_component_circuit,
        record=record_component_call_result,
        now_ms=clock.now_ms,
    )
    read_projection = ConnectorReadProjection(
        connector_reader=connector_reader,
        tool_registry=connector_bundle.tool_registry,
    )
    dispatch_connector_write = DispatchConnectorWriteHandler(
        unit_of_work_factory=unit_of_work_factory,
        tool_registry=connector_bundle.tool_registry,
        connector_write_port=connector_writer,
    )
    write_projection = ConnectorWriteProjection(
        dispatch_connector_write=dispatch_connector_write,
        connector_reader=read_projection,
    )
    structured_inference_router = cast(StructuredInferenceRuntimeRouter, llm_runtime)
    structured_inference_router.checkpoint = checkpoint

    def _llm_circuit_key(runtime: ActualRuntime) -> ComponentCircuitKey:
        return ComponentCircuitKey(1, "LLM_RUNTIME", None, runtime.value)

    def _check_llm_circuit(runtime: ActualRuntime) -> None:
        key = _llm_circuit_key(runtime)
        if check_component_circuit(CheckComponentCircuitQueryV1(1, key, clock.now_ms())).allowed:
            return
        raise LLMInvocationError(
            code=(
                LLMErrorCode.LOCAL_UNAVAILABLE
                if runtime is ActualRuntime.LOCAL_GPU
                else LLMErrorCode.PROVIDER_UNAVAILABLE
            ),
            message="component circuit is open",
        )

    def _record_llm_circuit_result(runtime: ActualRuntime, error_code: str | None) -> None:
        record_component_call_result(
            RecordComponentCallResultCommandV1(
                1,
                _llm_circuit_key(runtime),
                "SUCCESS" if error_code is None else "TECHNICAL_FAILURE",
                error_code,
                clock.now_ms(),
            )
        )

    structured_inference_router.before_runtime_dispatch = _check_llm_circuit
    structured_inference_router.record_runtime_result = _record_llm_circuit_result
    event_publisher = InMemorySseEventBuffer(service_instance_id=service_instance_id)
    retrieval_cache = InMemoryRunRetrievalCache()

    project_external_llm_transfer_scope = ProjectExternalLlmTransferScopeHandler(
        checkpoint,
        ProjectRunEventHandler(event_publisher),
    )
    project_context_preview = ProjectContextPreviewHandler(
        unit_of_work_factory=read_unit_of_work_factory,
        checkpoint=checkpoint,
    )
    project_recovery_options = ProjectRecoveryOptionsHandler(read_unit_of_work_factory)
    project_error_actions = ProjectErrorActionsHandler(
        unit_of_work_factory=read_unit_of_work_factory,
        checkpoint_port=checkpoint,
        resume_target_registry=resume_target_registry,
    )
    get_run_snapshot_handler = GetRunSnapshotHandler(
        unit_of_work_factory=read_unit_of_work_factory,
        project_context_preview=project_context_preview,
        project_recovery_options=project_recovery_options,
        project_error_actions=project_error_actions,
        project_external_llm_transfer_scope=project_external_llm_transfer_scope,
        resolve_pending_confirmation=lambda run_id: workflow_runtime.resolve_pending_confirmation(
            run_id
        ),
        tool_registry=connector_bundle.tool_registry,
    )

    def work_hours_provider() -> CalendarWorkHours:
        settings = settings_service.get_settings()
        return CalendarWorkHours(
            timezone=settings.timezone,
            days=tuple(range(7)) if settings.include_weekends else (0, 1, 2, 3, 4),
            start=settings.working_day_start_local,
            end=settings.working_day_end_local,
        )

    runtime_hooks = WorkflowRuntimeHooks()
    workflow_application_services = _build_workflow_application_services(
        unit_of_work_factory=unit_of_work_factory,
        get_run_snapshot=get_run_snapshot_handler,
        connector_reader=read_projection,
        tool_catalog=connector_bundle.tool_registry,
        now_ms=clock.now_ms,
        id_factory=id_generator.new_uuid,
        service_instance_id=service_instance_id,
        checkpoint=checkpoint,
        resume_target_registry=resume_target_registry,
        runtime_hooks=runtime_hooks,
        claim_context_signer=google_connector.client.sign_claim_context,
        work_hours_provider=work_hours_provider,
        sse_event_buffer=event_publisher,
        environment=oauth_environment.value,
        release_version=release_version,
    )
    try:
        workflow_runtime = LangGraphWorkflowRuntime(
            unit_of_work_factory=unit_of_work_factory,
            llm_runtime=llm_runtime,
            connector_reader=read_projection,
            connector_execution=write_projection,
            tool_catalog=connector_bundle.tool_registry,
            now_ms=clock.now_ms,
            id_factory=id_generator.new_uuid,
            signing_secret=secrets.token_hex(32),
            service_instance_id=service_instance_id,
            application_services=workflow_application_services,
            runtime_hooks=runtime_hooks,
            claim_context_signer=google_connector.client.sign_claim_context,
            mcp_process_instance_id=lambda: (
                google_connector.client.process_instance_id
                or (_ for _ in ()).throw(RuntimeError("MCP process identity is unavailable"))
            ),
            checkpoint_port=checkpoint,
            retrieval_cache=retrieval_cache,
            prompt_manifest_path=prompt_manifest_path,
            timezone_provider=lambda: settings_service.get_settings().timezone,
            work_hours_provider=work_hours_provider,
            default_tasklist_id_provider=lambda: (
                settings_service.get_settings().default_tasklist_id
            ),
            attachment_verifier=attachment_staging,
            resume_target_registry=resume_target_registry,
            sse_event_buffer=event_publisher,
            environment=oauth_environment.value,
            release_version=release_version,
            graph_profile=graph_profile,
        )
    except InactivePromptArtifactError:
        prompt_active = False
        workflow_runtime = _PromptInactiveWorkflowRuntime()

    def _project_external_scope(
        run_id: str,
        source_kinds: tuple[str, ...],
        data_classes: tuple[str, ...],
    ) -> ExternalLlmTransferScopeV1:
        scope = project_external_llm_transfer_scope(
            ProjectExternalLlmTransferScopeQueryV1(
                schema_version=1,
                run_id=run_id,
                source_kinds=source_kinds,
                data_classes=cast(Any, data_classes),
                occurred_at_ms=clock.now_ms(),
            )
        )
        if scope is None:
            raise RuntimeError("external LLM transfer scope was not projected")
        return scope

    llm_runtime.external_scope_projector = _project_external_scope
    require_recovery = _build_require_recovery(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint=checkpoint,
        now_ms=clock.now_ms,
        resume_target_registry=resume_target_registry,
    )

    def _workflow_recovery_target(run_id: str) -> RegisteredResumeTargetRefV2 | None:
        binding = checkpoint.load_workflow_binding(run_id)
        if binding is None:
            return None
        return resume_target_registry.issue_main_stage(
            binding.graph_profile,
            "RECOVERY",
            binding.graph_version,
        )

    outcome_handler = WorkflowOutcomeProjector(
        require_recovery=require_recovery,
        project_run_event=ProjectRunEventHandler(event_publisher),
        now_ms=clock.now_ms,
        id_factory=id_generator.new_uuid,
        recovery_target=_workflow_recovery_target,
    )

    def _start_request(admission: WorkflowExecutionAdmissionV1) -> WorkflowStartRequest:
        binding = admission.effective_binding
        context = get_execution_context(GetExecutionContextQuery(binding.run_id))
        if (
            context is None
            or context.workflow_key != binding.langgraph_thread_id
            or context.requested_mode != binding.requested_mode
        ):
            raise ValueError("persisted admission does not match Run execution context")
        return WorkflowStartRequest(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            workflow_key=context.workflow_key,
            entry_mode=context.entry_mode,
            requested_mode=context.requested_mode,
            request_text=context.request_text,
            selected_resource_ids=context.selected_resource_ids,
            run_budget=dict(context.run_budget),
            correlation=WorkflowCorrelationContext(
                request_id=admission.admission_id,
                command_id=admission.handoff_id,
                api_contract_version=api_contract_version,
            ),
            selected_resources=context.selected_resources,
        )

    def _initial_target(admission: WorkflowExecutionAdmissionV1) -> AgentNodeResumeTargetV2:
        profile = admission.effective_binding.graph_profile
        return resume_target_registry.issue_agent_node(
            profile,
            "REQUEST_UNDERSTANDING",
            "request.identify_goal",
            admission.effective_binding.graph_version,
        )

    def _materialize_admission_checkpoint(
        admission: WorkflowExecutionAdmissionV1,
        handoff: WorkflowHandoffV1,
    ) -> Any:
        binding = admission.effective_binding
        if binding.execution_kind == "START":
            target = _initial_target(admission)
            with checkpoint.execution_scope(
                admission,
                applied_handoff_id=admission.handoff_id,
                owner_scope="REQUEST_UNDERSTANDING",
                resume_target=target,
            ):
                workflow_runtime.prepare_start(_start_request(admission))
        elif admission.submission_kind == "NORMAL_HANDOFF":
            materialized = checkpoint.load_same_run_checkpoint(
                binding.run_id, binding.langgraph_thread_id
            )
            if materialized is None:
                raise RuntimeError("RESUME requires a native checkpoint")
            resume_target = binding.resume_target
            if resume_target is None:
                raise ValueError("RESUME admission requires a registered target")
            goto_node = _native_resume_node(resume_target)
            if handoff.control is None:
                checkpoint_control.materialize_resume_target(materialized, goto_node=goto_node)
            else:
                checkpoint_control.materialize_control(
                    materialized,
                    handoff.control,
                    goto_node=None
                    if handoff.control.kind == "CONFIRMATION_RESPONSE"
                    else goto_node,
                )
        materialized = checkpoint.load_same_run_checkpoint(
            binding.run_id, binding.langgraph_thread_id
        )
        if materialized is None:
            raise RuntimeError("admission did not materialize a native checkpoint")
        return materialized

    def _native_resume_node(resume_target: RegisteredResumeTargetRefV2) -> str:
        return cast(
            str,
            workflow_runtime.control_resume_node(resume_target.stage_id)
            if resume_target.kind == "MAIN_CONTROL"
            else workflow_runtime.agent_resume_node(resume_target.semantic_owner_id),
        )

    def _invoke_semantic_owner(
        admission: WorkflowExecutionAdmissionV1, handoff: WorkflowHandoffV1
    ) -> None:
        binding = admission.effective_binding
        context = get_execution_context(GetExecutionContextQuery(binding.run_id))
        if (
            context is None
            or context.workflow_key != binding.langgraph_thread_id
            or context.requested_mode != binding.requested_mode
        ):
            return
        target = binding.resume_target
        try:
            correlation = WorkflowCorrelationContext(
                request_id=admission.admission_id,
                command_id=admission.handoff_id,
                api_contract_version=api_contract_version,
            )
            latest = checkpoint.load_same_run_checkpoint(
                binding.run_id, binding.langgraph_thread_id
            )
            target = (
                _initial_target(admission)
                if binding.execution_kind == "START"
                else binding.resume_target
            )
            if target is None:
                raise ValueError("persisted admission has no registered resume target")
            with checkpoint.execution_scope(
                admission,
                applied_handoff_id=admission.handoff_id
                if admission.submission_kind == "NORMAL_HANDOFF"
                else None
                if latest is None
                else latest.applied_handoff_id,
                owner_scope=latest.owner_scope if latest is not None else "REQUEST_UNDERSTANDING",
                resume_target=target,
            ):
                if binding.execution_kind == "START":
                    result = workflow_runtime.start(_start_request(admission))
                else:
                    # Crash recovery must never replay an already-consumed
                    # one-shot control. A normal handoff, however, has just
                    # settled its durable materialization and must now execute
                    # that exact target/control against the compiled graph.
                    is_normal_handoff = admission.submission_kind == "NORMAL_HANDOFF"
                    resume_kind = (
                        "NORMAL_HANDOFF" if is_normal_handoff else "CONSUMED_CONTINUATION_RECOVERY"
                    )
                    resume_payload: dict[str, Any] = {}
                    result = workflow_runtime.resume(
                        WorkflowResumeRequest(
                            run_id=context.run_id,
                            workflow_key=context.workflow_key,
                            resume_kind=resume_kind,
                            resume_payload=resume_payload,
                            correlation=correlation,
                            normal_handoff_target_node=(
                                _native_resume_node(target) if is_normal_handoff else None
                            ),
                            normal_handoff_control=(handoff.control if is_normal_handoff else None),
                        )
                    )
        except Exception as error:
            LOGGER.exception(
                "workflow semantic owner invocation failed",
                extra={
                    "run_id": binding.run_id,
                    "handoff_id": admission.handoff_id,
                    "submission_kind": admission.submission_kind,
                },
            )
            current = get_execution_context(GetExecutionContextQuery(binding.run_id))
            outcome_handler.handle_result(
                binding.run_id,
                WorkflowOutcome.FAILED,
                {"error_code": "INTERNAL_ERROR", "message": str(error)[:200]},
                context.version if current is None else current.version,
            )
            return
        current = get_execution_context(GetExecutionContextQuery(binding.run_id))
        outcome_handler.handle_result(
            binding.run_id,
            result.outcome,
            result.payload,
            context.version if current is None else current.version,
        )

    production_runtime = _build_workflow_runtime(
        unit_of_work_factory=unit_of_work_factory,
        id_factory=id_generator.new_uuid,
        checkpoint=checkpoint,
        retrieval_cache=retrieval_cache,
        materialize_admission_checkpoint=_materialize_admission_checkpoint,
        invoke_semantic_owner=_invoke_semantic_owner,
        resume_target_registry=resume_target_registry,
        lookup_unknown_result=LookupUnknownResultHandler(
            connector_read=connector_reader,
            tool_registry=connector_bundle.tool_registry,
            recovery_search_binding=google_workspace_internal_read_binding(
                "search_by_recovery_fingerprint"
            ),
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        recover_existing_result=RecoverExistingResultHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        resolve_as_failed=ResolveAsFailedHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        require_recovery=require_recovery,
        materialize_recovery_snapshot=lambda tool_name, arguments, resource_id: (
            write_projection.materialize_recovery_candidate(
                tool_name=tool_name,
                arguments=arguments,
                resource_id=resource_id,
            )
        ),
        now_ms=clock.now_ms,
    )

    async def _reconcile_inflight_executions() -> None:
        await asyncio.to_thread(
            inflight_reconciliation.drain_inflight_executions_to_quiescence,
            production_runtime.reconcile_inflight_executions,
        )

    async def _drain_workflow_handoffs() -> None:
        await asyncio.to_thread(
            drain_workflow_handoffs_to_quiescence,
            production_runtime.redrive_workflow_handoffs,
        )

    async def _start_workflow_handoff_reconciliation_loop() -> None:
        production_runtime.workflow_handoff_reconciliation_loop.start()

    def _stop_workflow_handoff_runtime() -> None:
        production_runtime.workflow_handoff_reconciliation_loop.stop()
        production_runtime.workflow_execution.begin_shutdown()
        production_runtime.workflow_execution.await_drained(5_000)
        production_runtime.workflow_execution.close()

    session_manager = InMemoryLocalSessionManager()
    grant_store = InMemoryBootstrapGrantStore()
    grant_store.provision(
        secret=bootstrap_secret,
        service_instance_id=service_instance_id,
        now_ms=clock.now_ms(),
    )
    selection_handle_secret = secrets.token_bytes(32)
    issue_selection_handle = IssueSelectionHandle(
        signing_secret=selection_handle_secret,
        service_instance_id=service_instance_id,
        now_ms=clock.now_ms,
        ttl_ms=5 * 60 * 1000,
    )
    resolve_selection_handle = ResolveSelectionHandle(
        signing_secret=selection_handle_secret,
        service_instance_id=service_instance_id,
        now_ms=clock.now_ms,
    )

    def _checkpoint_domain_wal() -> None:
        with connect_sqlite(database_path) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    def _await_workflow_drain(timeout: float) -> None:
        production_runtime.workflow_execution.await_drained(int(timeout * 1_000))

    shutdown_adapter = ProcessShutdownAdapter(
        command_gate=_ShutdownComponent(),
        coordinator=_ShutdownComponent(
            stop_coordinator=production_runtime.workflow_execution.begin_shutdown,
            await_coordinator=_await_workflow_drain,
        ),
        workflow_runtime=_ShutdownComponent(flush_runtime=checkpoint.flush),
        observability=_ShutdownComponent(),
        persistence=_ShutdownComponent(checkpoint_persistence=_checkpoint_domain_wal),
        mcp_transport=_ShutdownComponent(close_component=connector_registry.close_all),
        sessions=_ShutdownComponent(invalidate_sessions=session_manager.invalidate_all),
        clock=clock,
        marker_path=root / "shutdown" / "request.json",
        request_process_exit=request_process_exit,
    )
    maintenance_gate = ProcessMaintenanceGateAdapter(
        has_active_write=production_runtime.workflow_execution.has_active_runs
    )
    backup_adapter = FilesystemBackupAdapter(
        database_path=database_path,
        backups_dir=root / "backups",
        clock=clock,
        maintenance_gate=maintenance_gate,
        release_version=release_version,
        domain_contract_version="1",
        schema_version=actual_database_migration_version,
        supported_restore_schema_versions=("0018", actual_database_migration_version),
    )

    resource_continuations = LocalResourceContinuationStore(now_ms=clock.now_ms)
    resource_access = OpaqueConnectorResourceAccess(
        ConnectorResourceAccess(
            gateway=read_projection,
            default_calendar_id_provider=(
                lambda: llm_runtime.settings_service().default_calendar_id
            ),
            default_tasklist_id_provider=(
                lambda: llm_runtime.settings_service().default_tasklist_id
            ),
            timezone_provider=lambda: llm_runtime.settings_service().timezone,
        ),
        continuation_store=resource_continuations,
    )
    start_run_handler = StartRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=clock.now_ms,
        id_factory=id_generator.new_uuid,
        graph_profile=graph_profile.value,
        graph_version=RESUME_CONTRACT_VERSION,
        settings_provider=settings_service.get_settings,
    )
    get_execution_context = get_run_snapshot_handler.execution_context

    def _resolve_resume_authority(*, run_id: str, resume_kind: str) -> dict[str, object] | None:
        if resume_kind != "REAUTH_COMPLETED":
            return None
        context = get_execution_context(GetExecutionContextQuery(run_id=run_id))
        resolver = getattr(workflow_runtime, "resolve_resume_authority", None)
        if context is None or not callable(resolver):
            return None
        return cast(
            dict[str, object] | None,
            resolver(
                run_id=run_id,
                workflow_key=context.workflow_key,
                resume_kind=resume_kind,
            ),
        )

    continue_cancel_resolution = getattr(
        workflow_runtime, "continue_graphless_bootstrap_cancel", None
    )
    project_run_event = ProjectRunEventHandler(event_publisher)
    resolve_recovery_handler = ResolveRecoveryHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=clock.now_ms,
        next_id=id_generator.new_uuid,
        resume_target_registry=resume_target_registry,
        schedule_run_execution=production_runtime.schedule_run_execution,
    )
    resume_confirmation_handler = ResumeConfirmationHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint_port=checkpoint,
        now_ms=clock.now_ms,
        id_factory=id_generator.new_uuid,
        resume_target_registry=resume_target_registry,
    )

    return ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        read_unit_of_work_factory=read_unit_of_work_factory,
        settings_port=settings_service,
        structured_inference_port=structured_inference_router,
        llm_runtime_selection=runtime_selection,
        create_conversation_handler=CreateConversationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        graph_profile=graph_profile.value,
        graph_version=RESUME_CONTRACT_VERSION,
        schedule_run_execution=production_runtime.schedule_run_execution,
        resume_target_registry=resume_target_registry,
        checkpoint_port=checkpoint,
        approve_action_service=None,
        modify_action_service=None,
        reject_action_service=None,
        prepare_retry_service=None,
        cancel_run_service=None,
        resume_run_service=None,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        action_gateway=read_projection,
        readiness_aggregator=LocalServiceReadinessAggregator(
            database_path=database_path,
            connector_registry=connector_registry,
            project_root=working_directory.resolve(),
            api_contract_version=api_contract_version,
            mcp_manifest_version=mcp_manifest_version,
            mcp_manifest_path=mcp_manifest_path,
            mcp_executable_path=mcp_executable_path,
            prompt_active=prompt_active,
            keyring_store=active_keyring_store,
        ),
        api_access_guard=LocalApiAccessGuard(
            expected_host=f"{host}:{port}",
            expected_origin=f"http://{host}:{port}",
            service_instance_id=service_instance_id,
            session_manager=session_manager,
            release_version=release_version,
            environment=oauth_environment.value,
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=id_generator,
        release_version=release_version,
        environment=oauth_environment.value,
        service_instance_id=service_instance_id,
        max_attachment_bytes=MAX_STAGED_FILE_BYTES,
        local_bind_host=host,
        local_bind_port=port,
        launcher_probe_verifier=ServiceInstanceLauncherProbeVerifier(service_instance_id),
        bootstrap_grant_store=grant_store,
        local_session_manager=session_manager,
        oauth_environment=oauth_environment,
        oauth_requested_scopes=_google_oauth_scopes(connector_bundle.tool_registry),
        start_authorization_handler=StartAuthorizationHandler(
            credentials=google_provider,
            replay=operational_replay,
        ),
        get_connection_status_handler=get_connection_status,
        current_account_id_provider=current_account_id,
        revoke_connection_handler=RevokeConnectionHandler(
            credentials=google_provider,
            replay=operational_replay,
            connected_account_store_factory=connected_account_store_factory,
            now_ms=clock.now_ms,
        ),
        list_resources_handler=ListResourcesHandler(resource_access),
        get_resource_count_handler=GetResourceCountHandler(resource_access),
        get_resource_detail_handler=GetResourceDetailHandler(resource_access),
        issue_selection_handle=issue_selection_handle,
        resolve_selection_handle=resolve_selection_handle,
        list_task_lists_handler=ListTaskListsHandler(
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
            continuation_store=resource_continuations,
        ),
        list_calendars_handler=ListCalendarsHandler(
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
            continuation_store=resource_continuations,
        ),
        get_task_resource_detail_handler=GetTaskResourceDetailHandler(
            resolve_handle=resolve_selection_handle,
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
        ),
        get_calendar_resource_detail_handler=GetCalendarResourceDetailHandler(
            resolve_handle=resolve_selection_handle,
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
        ),
        get_attachment_handler=GetAttachmentHandler(
            connector_read=connector_reader,
            tool_registry=connector_bundle.tool_registry,
        ),
        create_staged_attachment_handler=CreateStagedAttachmentHandler(
            staging=attachment_staging,
            replay=operational_replay,
        ),
        list_conversations_handler=ListConversationsHandler(
            unit_of_work_factory=read_unit_of_work_factory,
        ),
        get_conversation_history_handler=GetConversationHistoryHandler(
            unit_of_work_factory=read_unit_of_work_factory,
            history_message_limit=HISTORY_MESSAGE_LIMIT,
            history_run_limit=HISTORY_RUN_LIMIT,
        ),
        start_run_handler=start_run_handler,
        get_run_snapshot_handler=get_run_snapshot_handler,
        get_execution_context_handler=get_execution_context,
        list_run_events_handler=ListRunEventsHandler(
            unit_of_work_factory=read_unit_of_work_factory,
            event_buffer=event_publisher,
        ),
        project_context_preview_handler=project_context_preview,
        adjust_context_handler=AdjustContextHandler(
            unit_of_work_factory=unit_of_work_factory,
            project_context_preview=project_context_preview,
            begin_planning=BeginPlanningHandler(
                unit_of_work_factory=unit_of_work_factory,
                checkpoint_port=checkpoint,
                now_ms=clock.now_ms,
                id_factory=id_generator.new_uuid,
                resume_target_registry=resume_target_registry,
            ),
            schedule_run_execution=production_runtime.schedule_run_execution,
        ),
        request_cancel_handler=RequestCancelHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
            continue_cancel_resolution=continue_cancel_resolution,
        ),
        resume_safe_checkpoint_handler=ResumeSafeCheckpointHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
            id_factory=id_generator.new_uuid,
            operational_replay=operational_replay,
            now_ms=clock.now_ms,
        ),
        resume_after_reauth_handler=ResumeAfterReauthHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            resolve_resume_authority=_resolve_resume_authority,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
        ),
        resolve_recovery_handler=resolve_recovery_handler,
        confirm_run_handler=ConfirmRunHandler(
            resolve_pending_confirmation=workflow_runtime.resolve_pending_confirmation,
            resume_confirmation=resume_confirmation_handler,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
            id_factory=id_generator.new_uuid,
        ),
        approve_action_handler=ApproveActionHandler(
            get_approval_ttl_minutes=lambda: approval_policy_config.approval_ttl_minutes,
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
        ),
        modify_action_handler=ModifyActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            gateway=read_projection,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
            work_hours_provider=lambda: CalendarWorkHours(
                timezone=settings_service.get_settings().timezone,
                days=(
                    tuple(range(7))
                    if settings_service.get_settings().include_weekends
                    else (0, 1, 2, 3, 4)
                ),
                start=settings_service.get_settings().working_day_start_local,
                end=settings_service.get_settings().working_day_end_local,
            ),
        ),
        reject_action_handler=RejectActionHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
            project_run_event=project_run_event,
        ),
        prepare_write_retry_handler=PrepareWriteRetryHandler(
            unit_of_work_factory=unit_of_work_factory,
            checkpoint_port=checkpoint,
            now_ms=clock.now_ms,
            id_generator=id_generator,
            resume_target_registry=resume_target_registry,
            schedule_run_execution=production_runtime.schedule_run_execution,
        ),
        project_recovery_options_handler=project_recovery_options,
        project_error_actions_handler=project_error_actions,
        project_external_llm_transfer_scope_handler=project_external_llm_transfer_scope,
        get_llm_credential_status_handler=GetLlmCredentialStatusHandler(credential_service),
        get_settings_handler=GetSettingsHandler(settings_service),
        update_settings_handler=UpdateSettingsHandler(
            settings=settings_service,
            replay=operational_replay,
        ),
        list_backups_handler=ListBackupsHandler(backup_adapter),
        create_backup_handler=CreateBackupHandler(
            backups=backup_adapter,
            replay=operational_replay,
        ),
        restore_backup_handler=RestoreBackupHandler(
            backups=backup_adapter,
            replay=operational_replay,
        ),
        create_diagnostic_bundle_handler=CreateDiagnosticBundleHandler(
            diagnostics=diagnostics_adapter,
            replay=operational_replay,
        ),
        request_shutdown_handler=RequestShutdownHandler(
            shutdown=shutdown_adapter,
            replay=operational_replay,
        ),
        store_llm_credential_handler=StoreLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
        delete_llm_credential_handler=DeleteLlmCredentialHandler(
            credentials=credential_service,
            replay=operational_replay,
        ),
        safe_mode_controller=safe_mode,
        get_runtime_status_handler=GetRuntimeStatusHandler(
            runtime_mode=runtime_mode,
            oauth=google_provider,
            llm_status=llm_status_service,
            circuits=component_circuits,
            service_instance_id=service_instance_id,
            release_version=release_version,
            frontend_build_version=release_version,
            api_contract_version=api_contract_version,
            deployment_profile=deployment_profile,
            recovery_required=lambda: safe_mode.snapshot().enabled,
            database_status=lambda: "READY",
            migration_status=lambda: "READY",
            sse_status=lambda: "READY",
            launcher_status=lambda: "READY",
            manifest_status=lambda: "UNAVAILABLE",
            safe_mode=lambda: safe_mode.snapshot().enabled,
            last_migration_status=lambda: "READY",
        ),
        update_runtime_mode_handler=UpdateRuntimeModeHandler(
            runtime_mode=runtime_mode,
            replay=operational_replay,
            has_active_run=production_runtime.workflow_execution.has_active_runs,
        ),
        operational_command_replay=operational_replay,
        frontend_site=frontend_site,
        continue_cancel_resolution_handler=continue_cancel_resolution,
        startup_callbacks=(
            _reconcile_inflight_executions,
            _drain_workflow_handoffs,
            _start_workflow_handoff_reconciliation_loop,
        ),
        shutdown_callbacks=(
            _stop_workflow_handoff_runtime,
            workflow_runtime.close,
            connector_registry.close_all,
        ),
    )


def _build_llm_runtime(
    *,
    settings_path: Path,
    prompt_manifest_path: Path,
    unit_of_work_factory: Callable[[], UnitOfWork],
    now_ms: Callable[[], int],
    environment: str,
    release_version: str,
    runtime_selection: LlmRuntimeSelectionV1,
    keyring_store: SecretStorePort | None = None,
) -> tuple[
    StructuredInferenceRuntimeRouter,
    JsonSettingsAdapter,
    LlmCredentialRouter,
    LlmRuntimeStatusRouter,
]:
    settings_service = JsonSettingsAdapter(
        store=FileSettingsStore(settings_path),
    )
    prompt_registry = PromptRegistry(prompt_manifest_path)

    credential_service = LlmCredentialRouter(
        provider_name="gemini",
        environment=environment,
        keyring_store=keyring_store
        or OsKeyringSecretStoreAdapter(
            service_name=keyring_service_name(
                environment=environment,
                credential_type="llm-api-key",
            )
        ),
        session_store=SessionMemorySecretStore(),
    )
    ollama_transport = OllamaHTTPClient()
    ollama_probe = LoopbackOllamaProbe(transport=ollama_transport)
    gemini_transport = GeminiHTTPClient()
    hardware_probe = WindowsHardwareProbeAdapter(
        runtime_selection=runtime_selection,
        ollama_probe=ollama_probe,
    )
    status_service = LlmRuntimeStatusRouter(
        runtime_selection=runtime_selection,
        credential_service=credential_service,
        api_connection_service=GeminiConnectionService(transport=gemini_transport),
        hardware_probe=hardware_probe,
        runtime_policy=RuntimePolicy(),
        api_provider_name="gemini",
    )
    structured_inference = StructuredInferenceRuntimeRouter(
        before_provider_dispatch=account_provider_dispatch,
        run_context_provider=current_provider_dispatch_run_id,
        settings_service=settings_service.get_settings,
        runtime_selection=runtime_selection,
        status_service=status_service,
        credential_service=credential_service,
        hardware_probe=hardware_probe,
        api_provider_name="gemini",
        api_provider=GeminiStructuredInferenceAdapter(
            provider_name="gemini",
            transport=gemini_transport,
            model=DEFAULT_GEMINI_MODEL_ID,
            assemble_instruction_text=lambda prompt_ref, prompt_input: assemble_prompt(
                prompt_ref, prompt_input, registry=prompt_registry
            ),
        ),
        ollama_provider_factory=lambda model: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=runtime_selection.ollama_endpoint,
            model_id=model.model_id,
            assemble_instruction_text=lambda prompt_ref, prompt_input: assemble_prompt(
                prompt_ref, prompt_input, registry=prompt_registry
            ),
        ),
        runtime_policy=RuntimePolicy(),
        schema_repairer=PromptRepairSchemaRepairer(manifest_path=prompt_manifest_path),
        prompt_manifest_path=prompt_manifest_path,
        event_recorder=EmitTraceEventHandler(
            unit_of_work_factory=unit_of_work_factory,
            environment=environment,
            release_version=release_version,
            now_ms=now_ms,
        ),
    )
    return structured_inference, settings_service, credential_service, status_service


def _write_mcp_manifest(runtime_root: Path) -> Path:
    manifest_path = runtime_root / "mcp-manifest.json"
    registry = load_signed_tool_registry()
    manifest_path.write_text(
        json.dumps(
            build_manifest_payload_for_descriptors(
                connector_id="google_workspace",
                registry_manifest_hash=registry.entries_hash,
                descriptors=tuple(registry.descriptor_expectations("google_workspace")),
            ),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest_path.resolve()
