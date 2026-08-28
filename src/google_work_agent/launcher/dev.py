"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sqlite3
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

from fastapi import FastAPI

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    build_manifest_payload_for_descriptors,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import OsKeyringSecretStoreAdapter
from google_work_agent.adapters.langgraph.checkpoint_control import (
    LangGraphCheckpointControlAdapter,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.registry.checkpoint_target_resolver import (
    NativeCheckpointTargetResolver,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
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
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.persistence_exceptions import MigrationError
from google_work_agent.adapters.persistence.sqlite.query_service import QueryService
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.runtime import (
    BuildProfile,
    FileSettingsStore,
    SafeModeController,
)
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.filesystem_diagnostics import FilesystemDiagnosticsAdapter
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.json_settings import JsonSettingsAdapter
from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.adapters.system.process_component_circuit_state import (
    ProcessComponentCircuitStateAdapter,
)
from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter
from google_work_agent.adapters.system.process_shutdown import ProcessShutdownAdapter
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.adapters.system.system_clock import SystemClockAdapter
from google_work_agent.adapters.system.uuid4 import Uuid4Adapter
from google_work_agent.adapters.system.windows_hardware_probe import WindowsHardwareProbeAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import (
    build_production_runtime,
    drain_workflow_handoffs_to_quiescence,
)
from google_work_agent.api.container import API_CONTRACT_VERSION, ApiContainer
from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.application.connector_write_projection import ConnectorWriteProjection
from google_work_agent.application.coordinator_outcomes import RunOutcomeHandler
from google_work_agent.application.llm import (
    LLMRuntimeService,
    PromptRepairSchemaRepairer,
    TestLLMConnectionService,
)
from google_work_agent.application.observability import StaticMaintenanceGate
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.prompt_registry import (
    InactivePromptArtifactError,
    default_prompt_manifest_path,
    resolve_instruction_text,
)
from google_work_agent.application.policy_kernels.calendar_conflict import CalendarWorkHours
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.action.cancel_pending_action import (
    CancelPendingActionCommand,
    CancelPendingActionHandler,
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
from google_work_agent.application.use_cases.component_circuit.check_component_circuit import (
    CheckComponentCircuitHandler,
    CircuitProtectedConnectorReadPort,
    CircuitProtectedConnectorWritePort,
    CircuitProtectedStructuredInferencePort,
)
from google_work_agent.application.use_cases.component_circuit.record_component_call_result import (
    RecordComponentCallResultHandler,
)
from google_work_agent.application.use_cases.connection.get_connection_status import (
    GetConnectionStatusHandler,
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
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteHandler,
)
from google_work_agent.application.use_cases.execution_attempt.reconcile_inflight_executions import (  # noqa: E501
    ReconcileInflightExecutionsCommand,
    drain_inflight_executions_to_quiescence,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
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
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
)
from google_work_agent.application.use_cases.resource.connector_resource_access import (
    ConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.get_calendar_resource_detail import (
    GetCalendarResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.get_task_resource_detail import (
    GetTaskResourceDetailHandler,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    IssueSelectionHandle,
)
from google_work_agent.application.use_cases.resource.list_calendars import ListCalendarsHandler
from google_work_agent.application.use_cases.resource.list_task_lists import ListTaskListsHandler
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    OpaqueConnectorResourceAccess,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
)
from google_work_agent.application.use_cases.run.adjust_context import AdjustContextHandler
from google_work_agent.application.use_cases.run.begin_planning import BeginPlanningHandler
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionCommandV1,
    ContinueCancelResolutionHandler,
)
from google_work_agent.application.use_cases.run.finalize_cancel import (
    FinalizeCancelCommand,
    FinalizeCancelHandler,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
)
from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
)
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
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventHandler,
)
from google_work_agent.application.use_cases.trace_event.emit_trace_event import (
    EmitTraceEventHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.launcher.connector_composition import build_connectors
from google_work_agent.launcher.development_constants import (
    PROJECT_ROOT,
)
from google_work_agent.launcher.development_readiness import (
    DevelopmentReadinessAggregator as DevelopmentReadinessAggregator,
)
from google_work_agent.ports import (
    ApprovedModelInfo,
    AppSettings,
    LauncherProbeDecision,
    ReadinessAggregator,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimePolicy,
    RuntimeStatusProvider,
    RuntimeSummary,
    WorkflowCancelRequest,
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
    WorkHours,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPortError
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffV1,
)
from google_work_agent.ports.system.settings_port import SettingsViewV1

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
RELEASE_VERSION = "0.1.0-dev"
# Dev-mode local model allowlist: LOCAL_GPU routing refuses to invoke a model
# that is not "approved" (the structured-inference router's local-runtime gate),
# so at least one already-`ollama pull`-ed model must be listed here. This never
# pulls or downloads anything; override via env var if a different model is
# installed locally.
DEFAULT_DEV_OLLAMA_MODEL_ID = os.environ.get("GWA_DEV_APPROVED_OLLAMA_MODEL", "qwen2.5:3b")


@dataclass(frozen=True, slots=True)
class DevelopmentLauncherProbeVerifier:
    """Bind direct development readiness to this service instance."""

    service_instance_id: str

    def verify(self, *, service_instance_id: str) -> LauncherProbeDecision:
        return LauncherProbeDecision(allowed=service_instance_id == self.service_instance_id)


class CoreInitializationError(RuntimeError):
    """Redacted core-startup failure exposed through readiness only."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


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


class _BootReadinessAggregator(ReadinessAggregator):
    """Expose initialization state without making liveness depend on core startup."""

    def __init__(self, safe_mode: SafeModeController) -> None:
        self._safe_mode = safe_mode
        self._delegate: ReadinessAggregator | None = None
        self._failure_code: str | None = None

    def bind(self, delegate: ReadinessAggregator) -> None:
        self._delegate = delegate

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


class _BootRuntimeStatusProvider:
    def get_summary(self) -> RuntimeSummary:
        return RuntimeSummary(
            google="NOT_CONFIGURED",
            mcp="INITIALIZING",
            api_llm="NOT_CONFIGURED",
            ollama="NOT_CONFIGURED",
            deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
            recovery_required_run_ids=(),
            open_run_ids=(),
            safe_mode=True,
            safe_mode_reason_codes=("CORE_INITIALIZING",),
        )


class _BootQueryService:
    def get_runtime_summary(self) -> RuntimeSummary:
        return _BootRuntimeStatusProvider().get_summary()


class _DeferredApiContainer:
    """Stable DI shell used by FastAPI while the concrete core is built."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        service_instance_id: str,
        bootstrap_secret: str,
        core_builder: Callable[..., ApiContainer] | None = None,
    ) -> None:
        self._core: ApiContainer | None = None
        self._core_builder = core_builder
        self._closed = False
        self.safe_mode_controller = SafeModeController()
        self.core_initialization_in_progress = True
        self.readiness_aggregator = _BootReadinessAggregator(self.safe_mode_controller)
        self.runtime_status_provider: RuntimeStatusProvider = _BootRuntimeStatusProvider()
        self.query_service: Any = _BootQueryService()
        self.create_conversation_handler: Any = None
        self.list_conversations_handler: Any = None
        self.get_conversation_history_handler: Any = None
        self.clock = SystemClockAdapter()
        self.id_generator = Uuid4Adapter()
        self.release_version = RELEASE_VERSION
        self.environment = "DEVELOPMENT"
        self.service_instance_id = service_instance_id
        self.api_contract_version = API_CONTRACT_VERSION
        self.local_bind_host = host
        self.local_bind_port = port
        self.max_request_body_bytes = 64 * 1024
        self.api_docs_enabled = False
        self.frontend_site = None
        self.additional_readiness_checks: tuple[Any, ...] = ()
        self.shutdown_callbacks = (self.close,)
        self.startup_callbacks = (self._initialize,)
        self.client_address_resolver: Callable[[Any], str | None] | None = None
        self.operational_log_sink = None
        self.endpoint_policy_registry = None
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
            release_version=RELEASE_VERSION,
            environment="DEVELOPMENT",
            now_ms=self.clock.now_ms,
        )
        self.launcher_probe_verifier = DevelopmentLauncherProbeVerifier(service_instance_id)
        self.bootstrap_grant_store = self._bootstrap_grant_store
        self.local_session_manager = self._session_manager

    async def _initialize(self) -> None:
        worker = asyncio.create_task(
            asyncio.to_thread(
                self._core_builder or build_container,
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
            return
        except Exception:
            self.core_initialization_in_progress = False
            self.safe_mode_controller.enable("CORE_INITIALIZATION_FAILED")
            self.readiness_aggregator.fail("CORE_INITIALIZATION_FAILED")
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
            return
        self._core = core
        self.readiness_aggregator.bind(core.readiness_aggregator)
        self.runtime_status_provider = core.runtime_status_provider
        self.query_service = core.query_service
        self.core_initialization_in_progress = False
        self.safe_mode_controller.disable()

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

    @staticmethod
    def _not_available(run_id: str, workflow_key: str) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=run_id,
            workflow_key=workflow_key,
            outcome=WorkflowOutcome.FAILED,
            payload={"safe_error_code": "PROMPT_NOT_ACTIVE"},
        )


def build_container(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    runtime_root: Path | None = None,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
    safe_mode_controller: SafeModeController | None = None,
) -> ApiContainer:
    """Assemble the development service with real local adapters."""

    LocalBindPolicy(host=host, port=port).validate()
    root = (runtime_root or PROJECT_ROOT / "runtime" / "development").resolve()
    root.mkdir(parents=True, exist_ok=True)
    database_path = root / "google-work-agent.sqlite3"
    mcp_manifest_path = _write_mcp_manifest(root)
    prompt_manifest_path = default_prompt_manifest_path()
    clock = SystemClockAdapter()
    id_generator = Uuid4Adapter()
    service_instance_id = service_instance_id or f"dev-{uuid.uuid4()}"
    attachment_staging_dir = root / "attachments" / "staging"
    attachment_staging = FilesystemAttachmentStagingAdapter(
        staging_dir=attachment_staging_dir,
        now_ms=clock.now_ms,
    )
    attachment_staging.cleanup_expired()
    operational_replay = FilesystemOperationalCommandReplayAdapter(
        root / "operational-command-replay"
    )

    try:
        with connect_sqlite(database_path) as connection:
            apply_migrations(connection, now_ms=clock.now_ms)
    except (sqlite3.Error, MigrationError) as error:
        raise CoreInitializationError("MIGRATION_FAILED") from error

    try:
        connector_bundle = build_connectors(
            mcp_manifest_path=mcp_manifest_path,
            service_instance_id=service_instance_id,
            attachment_staging_dir=attachment_staging_dir,
            python_executable=Path(sys.executable).resolve(),
            working_directory=PROJECT_ROOT,
        )
    except MCPClientPortError as error:
        raise CoreInitializationError("MCP_HANDSHAKE_FAILED") from error
    connector_registry = connector_bundle.runtime_registry
    google_connector = connector_bundle.google_connector
    runtime_status_provider = connector_bundle.runtime_status_provider
    google_provider = google_connector.oauth_port
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(
        database_path=database_path,
        connection_factory=connect_sqlite,
        runtime_status_provider=runtime_status_provider,
    )
    try:
        llm_runtime, settings_service = _build_llm_runtime(
            settings_path=root / "settings" / "app-settings.json",
            query_service=query_service,
            prompt_manifest_path=prompt_manifest_path,
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        )
    except RuntimeError as error:
        connector_registry.close_all()
        raise CoreInitializationError("KEYRING_UNAVAILABLE") from error
    runtime_mode = ProcessRuntimeModeAdapter(
        initial_mode=cast(Any, settings_service.get_settings().preferred_llm_mode)
    )
    component_circuits = ProcessComponentCircuitStateAdapter(
        failure_threshold=settings_service.get_settings().circuit_failure_threshold,
        open_duration_ms=settings_service.get_settings().circuit_open_duration_ms,
    )
    check_component_circuit = CheckComponentCircuitHandler(component_circuits)
    record_component_call_result = RecordComponentCallResultHandler(component_circuits)
    llm_runtime.structured_inference = CircuitProtectedStructuredInferencePort(
        delegate=llm_runtime.structured_inference,
        check=check_component_circuit,
        record=record_component_call_result,
        now_ms=clock.now_ms,
    )
    backup_adapter = FilesystemBackupAdapter(
        database_path=database_path,
        backups_dir=root / "backups",
        clock=clock,
        maintenance_gate=StaticMaintenanceGate(),
        release_version=RELEASE_VERSION,
        domain_contract_version="1",
        schema_version="1",
    )
    diagnostics_adapter = FilesystemDiagnosticsAdapter(
        collect_snapshot=lambda: {
            "release_version": RELEASE_VERSION,
            "environment": "DEVELOPMENT",
            "service_instance_id": service_instance_id,
        },
        diagnostics_dir=root / "diagnostics",
        now_ms=clock.now_ms,
        max_bundle_bytes=256 * 1024,
    )
    prompt_active = True
    workflow_runtime: LangGraphWorkflowRuntime | _PromptInactiveWorkflowRuntime
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
            claim_context_signer=google_connector.client.sign_claim_context,
            mcp_process_instance_id=lambda: (
                google_connector.client.process_instance_id
                or (_ for _ in ()).throw(RuntimeError("MCP process identity is unavailable"))
            ),
            checkpoint_port=checkpoint,
            prompt_manifest_path=prompt_manifest_path,
            timezone_provider=lambda: settings_service.get_settings().timezone,
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
            default_tasklist_id_provider=lambda: (
                settings_service.get_settings().default_tasklist_id
            ),
            attachment_verifier=attachment_staging,
            resume_target_registry=resume_target_registry,
        )
    except InactivePromptArtifactError:
        prompt_active = False
        workflow_runtime = _PromptInactiveWorkflowRuntime()
    event_publisher = InMemorySseEventBuffer(service_instance_id=service_instance_id)
    outcome_handler = RunOutcomeHandler(
        unit_of_work_factory=unit_of_work_factory,
        project_run_event=ProjectRunEventHandler(event_publisher),
        now_ms=clock.now_ms,
    )

    def _start_request(admission: WorkflowExecutionAdmissionV1) -> WorkflowStartRequest:
        binding = admission.effective_binding
        context = query_service.get_run_execution_context(binding.run_id)
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
            correlation=WorkflowCorrelationContext(
                request_id=admission.admission_id,
                command_id=admission.handoff_id,
                api_contract_version=API_CONTRACT_VERSION,
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
    ):
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
            target = binding.resume_target
            if target is None:
                raise ValueError("RESUME admission requires a registered target")
            goto_node = (
                workflow_runtime.control_resume_node(target.stage_id)
                if target.kind == "MAIN_CONTROL"
                else workflow_runtime.agent_resume_node(target.semantic_owner_id)
            )
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

    def _invoke_semantic_owner(
        admission: WorkflowExecutionAdmissionV1, handoff: WorkflowHandoffV1
    ) -> None:
        binding = admission.effective_binding
        context = query_service.get_run_execution_context(binding.run_id)
        if (
            context is None
            or context.workflow_key != binding.langgraph_thread_id
            or context.requested_mode != binding.requested_mode
        ):
            return
        target = binding.resume_target
        if (
            target is not None
            and target.kind == "MAIN_CONTROL"
            and target.stage_id == "CANCEL_RESOLUTION"
        ):
            for _ in range(256):
                cancel_result = continue_cancel_resolution(
                    ContinueCancelResolutionCommandV1(1, binding.run_id)
                )
                if cancel_result.outcome != "PROGRESSED":
                    break
            return
        try:
            correlation = WorkflowCorrelationContext(
                request_id=admission.admission_id,
                command_id=admission.handoff_id,
                api_contract_version=API_CONTRACT_VERSION,
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
                    # CONSUMED_CONTINUATION_RECOVERY is a crash-recovery
                    # re-submission of an *already-consumed* handoff -- its
                    # in-memory `handoff` object (fetched before consumption
                    # in BackgroundRunExecutorAdapter._consume) still carries
                    # the original one-shot control_kind/control, but that
                    # payload was already applied once and must never be
                    # replayed. Recovery resumes solely from the checkpoint-
                    # derived binding.resume_target (CheckpointEffectiveBindingResolver),
                    # never by re-reading the handoff's original control.
                    resume_kind = "CONSUMED_CONTINUATION_RECOVERY"
                    resume_payload = {}
                    result = workflow_runtime.resume(
                        WorkflowResumeRequest(
                            run_id=context.run_id,
                            workflow_key=context.workflow_key,
                            resume_kind=resume_kind,
                            resume_payload=resume_payload,
                            correlation=correlation,
                        )
                    )
        except Exception as error:
            current = query_service.get_run_execution_context(binding.run_id)
            outcome_handler.handle_result(
                binding.run_id,
                WorkflowOutcome.FAILED,
                {"error_code": "INTERNAL_ERROR", "message": str(error)[:200]},
                context.version if current is None else current.version,
            )
            return
        current = query_service.get_run_execution_context(binding.run_id)
        outcome_handler.handle_result(
            binding.run_id,
            result.outcome,
            result.payload,
            context.version if current is None else current.version,
        )

    production_runtime = build_production_runtime(
        unit_of_work_factory=unit_of_work_factory,
        id_factory=id_generator.new_uuid,
        checkpoint=checkpoint,
        materialize_admission_checkpoint=_materialize_admission_checkpoint,
        invoke_semantic_owner=_invoke_semantic_owner,
        resume_target_registry=resume_target_registry,
        lookup_unknown_result=LookupUnknownResultHandler(
            connector_read=connector_reader,
            tool_registry=connector_bundle.tool_registry,
        ),
        recover_existing_result=RecoverExistingResultHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        resolve_as_failed=ResolveAsFailedHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
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
            drain_inflight_executions_to_quiescence,
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
        production_runtime.checkpoint.close()

    session_manager = InMemoryLocalSessionManager()
    grant_store = InMemoryBootstrapGrantStore()
    secret = bootstrap_secret or secrets.token_urlsafe(32)
    grant_store.provision(
        secret=secret,
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
    cancel_pending_action = CancelPendingActionHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
    )
    finalize_cancel = FinalizeCancelHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=clock.now_ms,
    )
    continue_cancel_resolution = ContinueCancelResolutionHandler(
        unit_of_work_factory=unit_of_work_factory,
        settle_pending_action=lambda action_id, version: cancel_pending_action(
            CancelPendingActionCommand(
                command_id=f"system:cancel-resolution:action:{action_id}:{version}",
                request_hash=calculate_canonical_json_hash(
                    {"action_id": action_id, "expected_version": version}
                ),
                action_id=action_id,
                expected_version=version,
            )
        ).applied,
        reconcile_inflight_action=lambda _action_id: (
            production_runtime.reconcile_inflight_executions(
                ReconcileInflightExecutionsCommand(1, 256)
            ).progressed_count
            > 0
        ),
        verify_executed_action=lambda _action_id: (
            production_runtime.reconcile_inflight_executions(
                ReconcileInflightExecutionsCommand(1, 256)
            ).progressed_count
            > 0
        ),
        resolve_unknown_action=lambda _action_id: (
            production_runtime.reconcile_inflight_executions(
                ReconcileInflightExecutionsCommand(1, 256)
            ).progressed_count
            > 0
        ),
        finalize_cancel=lambda run_id, version: finalize_cancel(
            FinalizeCancelCommand(
                command_id=f"system:cancel-resolution:finalize:{run_id}:{version}",
                request_hash=calculate_canonical_json_hash(
                    {"run_id": run_id, "expected_run_version": version}
                ),
                run_id=run_id,
                expected_run_version=version,
            )
        ).applied,
    )
    project_context_preview = ProjectContextPreviewHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint=checkpoint,
    )

    def _checkpoint_domain_wal() -> None:
        with connect_sqlite(database_path) as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")

    shutdown_adapter = ProcessShutdownAdapter(
        command_gate=_ShutdownComponent(),
        coordinator=_ShutdownComponent(
            stop_coordinator=production_runtime.workflow_execution.begin_shutdown,
            await_coordinator=lambda timeout: production_runtime.workflow_execution.await_drained(
                int(timeout * 1_000)
            ),
        ),
        workflow_runtime=_ShutdownComponent(flush_runtime=checkpoint.flush),
        observability=_ShutdownComponent(),
        persistence=_ShutdownComponent(checkpoint_persistence=_checkpoint_domain_wal),
        mcp_transport=_ShutdownComponent(close_component=connector_registry.close_all),
        sessions=_ShutdownComponent(invalidate_sessions=session_manager.invalidate_all),
        clock=clock,
        marker_path=root / "shutdown" / "request.json",
    )

    return ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        query_service=query_service,
        create_conversation_handler=CreateConversationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        graph_profile=GraphProfile.SIX_ROLE_BASELINE.value,
        graph_version=RESUME_CONTRACT_VERSION,
        schedule_run_execution=production_runtime.schedule_run_execution,
        resume_target_registry=resume_target_registry,
        approve_action_service=None,
        modify_action_service=None,
        reject_action_service=None,
        prepare_retry_service=None,
        cancel_run_service=None,
        resume_run_service=None,
        workflow_runtime=workflow_runtime,
        event_publisher=event_publisher,
        action_gateway=read_projection,
        readiness_aggregator=DevelopmentReadinessAggregator(
            database_path=database_path,
            connector_registry=connector_registry,
            mcp_manifest_path=mcp_manifest_path,
            prompt_active=prompt_active,
        ),
        runtime_status_provider=runtime_status_provider,
        api_access_guard=LocalApiAccessGuard(
            expected_host=f"{host}:{port}",
            expected_origin=f"http://{host}:{port}",
            service_instance_id=service_instance_id,
            session_manager=session_manager,
            release_version=RELEASE_VERSION,
            environment="DEVELOPMENT",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=id_generator,
        release_version=RELEASE_VERSION,
        environment="DEVELOPMENT",
        service_instance_id=service_instance_id,
        local_bind_host=host,
        local_bind_port=port,
        launcher_probe_verifier=DevelopmentLauncherProbeVerifier(service_instance_id),
        bootstrap_grant_store=grant_store,
        local_session_manager=session_manager,
        start_authorization_handler=StartAuthorizationHandler(
            credentials=google_provider,
            replay=operational_replay,
        ),
        get_connection_status_handler=GetConnectionStatusHandler(google_provider),
        revoke_connection_handler=RevokeConnectionHandler(
            credentials=google_provider,
            replay=operational_replay,
        ),
        resource_query_service=OpaqueConnectorResourceAccess(
            ConnectorResourceAccess(
                gateway=read_projection,
                default_calendar_id_provider=(
                    lambda: llm_runtime.settings_service().default_calendar_id
                ),
                default_tasklist_id_provider=(
                    lambda: llm_runtime.settings_service().default_tasklist_id
                ),
                timezone_provider=lambda: llm_runtime.settings_service().timezone,
            )
        ),
        issue_selection_handle=issue_selection_handle,
        resolve_selection_handle=resolve_selection_handle,
        list_task_lists_handler=ListTaskListsHandler(
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
        ),
        list_calendars_handler=ListCalendarsHandler(
            connector_read=connector_reader,
            registry=connector_bundle.tool_registry,
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
            unit_of_work_factory=unit_of_work_factory,
        ),
        get_conversation_history_handler=GetConversationHistoryHandler(
            unit_of_work_factory=unit_of_work_factory,
        ),
        project_context_preview_handler=project_context_preview,
        adjust_context_handler=AdjustContextHandler(
            project_context_preview=project_context_preview,
            begin_planning=BeginPlanningHandler(
                unit_of_work_factory=unit_of_work_factory,
                now_ms=clock.now_ms,
                id_factory=id_generator.new_uuid,
                resume_target_registry=resume_target_registry,
            ),
            schedule_run_execution=production_runtime.schedule_run_execution,
        ),
        project_recovery_options_handler=ProjectRecoveryOptionsHandler(
            unit_of_work_factory
        ),
        project_error_actions_handler=ProjectErrorActionsHandler(),
        project_external_llm_transfer_scope_handler=(
            ProjectExternalLlmTransferScopeHandler(
                checkpoint,
                ProjectRunEventHandler(event_publisher),
            )
        ),
        get_llm_credential_status_handler=GetLlmCredentialStatusHandler(
            llm_runtime.credential_service
        ),
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
            credentials=llm_runtime.credential_service,
            replay=operational_replay,
        ),
        delete_llm_credential_handler=DeleteLlmCredentialHandler(
            credentials=llm_runtime.credential_service,
            replay=operational_replay,
        ),
        test_llm_connection_service=TestLLMConnectionService(runtime_service=llm_runtime),
        safe_mode_controller=safe_mode_controller,
        get_runtime_status_handler=GetRuntimeStatusHandler(
            runtime_mode=runtime_mode,
            oauth=google_provider,
            llm_status=llm_runtime.status_service,
            circuits=component_circuits,
        ),
        update_runtime_mode_handler=UpdateRuntimeModeHandler(
            runtime_mode=runtime_mode,
            replay=operational_replay,
        ),
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


def create_service_app() -> FastAPI:
    """Return an argument-free application factory for Uvicorn."""

    shell = _DeferredApiContainer(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=secrets.token_urlsafe(32),
    )
    return create_app(cast(ApiContainer, shell))


def main() -> NoReturn:
    """Run the development service on an explicit loopback address."""

    parser = argparse.ArgumentParser(description="Run the Google Work Agent development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    LocalBindPolicy(host=args.host, port=args.port).validate()
    bootstrap_secret = secrets.token_urlsafe(32)
    container = _DeferredApiContainer(
        host=args.host,
        port=args.port,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=bootstrap_secret,
    )
    print(
        "Open the Vite development UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={container.service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(create_app(cast(ApiContainer, container)), host=args.host, port=args.port)
    raise SystemExit(0)


def _close_container(container: ApiContainer) -> None:
    """Close core-owned resources exactly once when deferred startup loses a race."""

    for callback in container.shutdown_callbacks:
        callback()


def _build_llm_runtime(
    *,
    settings_path: Path,
    query_service: QueryService,
    prompt_manifest_path: Path,
    unit_of_work_factory: Callable[[], UnitOfWork],
    now_ms: Callable[[], int],
) -> tuple[LLMRuntimeService, JsonSettingsAdapter]:
    settings_service = JsonSettingsAdapter(
        store=FileSettingsStore(settings_path),
    )

    def runtime_settings() -> AppSettings:
        return _project_runtime_settings(settings_service.get_settings())

    credential_service = LlmCredentialRouter(
        provider_name="gemini",
        environment="DEVELOPMENT",
        keyring_store=OsKeyringSecretStoreAdapter(),
        session_store=SessionMemorySecretStore(),
    )
    ollama_transport = OllamaHTTPClient()
    gemini_transport = GeminiHTTPClient()
    status_service = LlmRuntimeStatusRouter(
        build_profile=BuildProfile.LOCAL_CAPABLE.value,
        settings_service=runtime_settings,
        credential_service=credential_service,
        api_connection_service=GeminiConnectionService(transport=gemini_transport),
        ollama_probe=LoopbackOllamaProbe(transport=ollama_transport),
        approved_models={
            DEFAULT_DEV_OLLAMA_MODEL_ID: ApprovedModelInfo(
                model_id=DEFAULT_DEV_OLLAMA_MODEL_ID,
                runtime="OLLAMA",
                manifest_version="1",
                schema_version="1",
            )
        },
        runtime_policy=RuntimePolicy(),
        api_provider_name="gemini",
    )
    structured_inference = StructuredInferenceRuntimeRouter(
        settings_service=runtime_settings,
        status_service=status_service,
        credential_service=credential_service,
        hardware_probe=WindowsHardwareProbeAdapter(),
        api_provider_name="gemini",
        api_provider=GeminiStructuredInferenceAdapter(
            provider_name="gemini",
            transport=gemini_transport,
            model=DEFAULT_GEMINI_MODEL_ID,
            resolve_instruction_text=lambda prompt_ref: resolve_instruction_text(
                prompt_ref.prompt_id, prompt_manifest_path
            ),
        ),
        ollama_provider_factory=lambda model, settings: OllamaStructuredInferenceAdapter(
            provider_name="ollama",
            transport=ollama_transport,
            endpoint=settings.ollama_endpoint or "http://127.0.0.1:11434",
            model_id=model.model_id,
            resolve_instruction_text=lambda prompt_ref: resolve_instruction_text(
                prompt_ref.prompt_id, prompt_manifest_path
            ),
        ),
        runtime_policy=RuntimePolicy(),
        schema_repairer=PromptRepairSchemaRepairer(manifest_path=prompt_manifest_path),
        prompt_manifest_path=prompt_manifest_path,
    )
    llm_runtime = LLMRuntimeService(
        settings_service=runtime_settings,
        status_service=status_service,
        credential_service=credential_service,
        ollama_provider_factory=structured_inference.ollama_provider_factory,
        structured_inference=structured_inference,
        runtime_policy=RuntimePolicy(),
        schema_repairer=PromptRepairSchemaRepairer(manifest_path=prompt_manifest_path),
        event_recorder=EmitTraceEventHandler(
            unit_of_work_factory=unit_of_work_factory,
            environment="DEVELOPMENT",
            release_version=RELEASE_VERSION,
            now_ms=now_ms,
        ),
    )
    return llm_runtime, settings_service


def _project_runtime_settings(settings: SettingsViewV1) -> AppSettings:
    """Project the canonical persisted settings into the still-broad LLM runtime input."""

    return AppSettings(
        deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
        requested_runtime_mode=settings.preferred_llm_mode,
        default_calendar_id=settings.default_calendar_id,
        default_tasklist_id=settings.default_tasklist_id,
        timezone=settings.timezone,
        work_hours=WorkHours(
            days=tuple(range(7)) if settings.include_weekends else (0, 1, 2, 3, 4),
            start=settings.working_day_start_local,
            end=settings.working_day_end_local,
        ),
        run_retention_days=settings.retention_days,
        external_llm_consent=settings.external_llm_consent,
    )


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


if __name__ == "__main__":
    main()
