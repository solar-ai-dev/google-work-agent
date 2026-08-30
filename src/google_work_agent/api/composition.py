"""Single concrete production composition authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.adapters.connectors.runtime.mcp_connector_read import McpConnectorReadAdapter
from google_work_agent.adapters.connectors.runtime.mcp_connector_write import (
    McpConnectorWriteAdapter,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import StdioMCPClientAdapter
from google_work_agent.adapters.keyring.os_keyring_secret_store import OsKeyringSecretStoreAdapter
from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import LlmCredentialRouter
from google_work_agent.adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter
from google_work_agent.adapters.llm.runtime.structured_inference_router import (
    StructuredInferenceRuntimeRouter,
)
from google_work_agent.adapters.system.default_browser_launcher import DefaultBrowserLauncherAdapter
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    FilesystemAttachmentStagingAdapter,
)
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.filesystem_diagnostics import FilesystemDiagnosticsAdapter
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.json_settings import JsonSettingsAdapter
from google_work_agent.adapters.system.memory.run_retrieval_cache import InMemoryRunRetrievalCache
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
from google_work_agent.adapters.system.workflow_handoff_reconciliation_loop import (
    WorkflowHandoffReconciliationLoop,
)
from google_work_agent.application.use_cases.execution_attempt.mark_unknown_result import (
    MarkUnknownResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.reconcile_inflight_executions import (  # noqa: E501
    ReconcileInflightExecutionsHandler,
)
from google_work_agent.application.use_cases.execution_attempt.recover_existing_result import (
    RecoverExistingResultHandler,
)
from google_work_agent.application.use_cases.execution_attempt.resolve_as_failed import (
    ResolveAsFailedHandler,
)
from google_work_agent.application.use_cases.recovery.lookup_unknown_result import (
    LookupUnknownResultHandler,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart import (
    ReconcileRetrievalCacheRestartHandler,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeTargetIssuer,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    CheckpointEffectiveBindingResolver,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.connector.connector_write_port import ConnectorWritePort
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort
from google_work_agent.ports.connector.oauth_credential_port import OAuthCredentialPort
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.llm.llm_credential_port import LlmCredentialPort
from google_work_agent.ports.llm.llm_runtime_status_port import LlmRuntimeStatusPort
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.attachment_staging_port import AttachmentStagingPort
from google_work_agent.ports.system.backup_port import BackupPort
from google_work_agent.ports.system.browser_launcher_port import BrowserLauncherPort
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.clock_port import ClockPort
from google_work_agent.ports.system.component_circuit_state_port import ComponentCircuitStatePort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffV1,
)
from google_work_agent.ports.system.diagnostics_port import DiagnosticsPort
from google_work_agent.ports.system.hardware_probe_port import HardwareProbePort
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort
from google_work_agent.ports.system.runtime_mode_port import RuntimeModePort
from google_work_agent.ports.system.settings_port import SettingsPort
from google_work_agent.ports.system.shutdown_port import ShutdownPort
from google_work_agent.ports.system.sse_event_buffer_port import SseEventBufferPort
from google_work_agent.ports.system.uuid_port import UUIDPort
from google_work_agent.ports.system.workflow_execution_port import WorkflowExecutionPort

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
    reconcile_inflight_executions: ReconcileInflightExecutionsHandler
    workflow_execution: BackgroundRunExecutorAdapter
    schedule_run_execution: ScheduleRunExecutionHandler
    redrive_workflow_handoffs: RedriveWorkflowHandoffsHandler
    workflow_handoff_reconciliation_loop: WorkflowHandoffReconciliationLoop


def build_production_runtime(
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
    require_recovery = RequireRecoveryHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=now_ms,
        resume_target_registry=resume_target_registry,
    )
    reconcile_retrieval_cache_restart = ReconcileRetrievalCacheRestartHandler(
        unit_of_work_factory=unit_of_work_factory,
        checkpoint=checkpoint,
        retrieval_cache=retrieval_cache,
        resume_target_registry=resume_target_registry,
        schedule_run_execution=schedule,
        id_factory=id_factory,
    )
    reconcile_inflight = ReconcileInflightExecutionsHandler(
        unit_of_work_factory=unit_of_work_factory,
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
