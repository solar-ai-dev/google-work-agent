"""Single concrete production composition authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.adapters.system.workflow_handoff_reconciliation_loop import (
    WorkflowHandoffReconciliationLoop,
)
from google_work_agent.application.use_cases.run.reconcile_blocked_binding import (
    ReconcileBlockedBindingHandler,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeTargetValidator,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    CheckpointEffectiveBindingResolver,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    WorkflowExecutionAdmissionV1,
    WorkflowHandoffV1,
)


@dataclass(frozen=True, slots=True)
class ProductionRuntime:
    checkpoint: SqliteCheckpointAdapter
    workflow_execution: BackgroundRunExecutorAdapter
    schedule_run_execution: ScheduleRunExecutionHandler
    redrive_workflow_handoffs: RedriveWorkflowHandoffsHandler
    workflow_handoff_reconciliation_loop: WorkflowHandoffReconciliationLoop


def build_production_runtime(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    id_factory: Callable[[], str],
    checkpoint: SqliteCheckpointAdapter,
    materialize_admission_checkpoint: Callable[
        [WorkflowExecutionAdmissionV1], GraphCheckpointEnvelopeV1
    ],
    invoke_semantic_owner: Callable[
        [WorkflowExecutionAdmissionV1, WorkflowHandoffV1], None
    ],
    resume_target_registry: ResumeTargetValidator,
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
    )
    reconcile_blocked_binding = ReconcileBlockedBindingHandler(
        unit_of_work_factory=unit_of_work_factory,
        require_recovery=require_recovery,
    )
    redrive = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=unit_of_work_factory,
        schedule_run_execution=schedule,
        reconcile_blocked_binding=reconcile_blocked_binding,
    )
    loop = WorkflowHandoffReconciliationLoop(
        redrive=redrive,
        interval_seconds=reconciliation_interval_seconds,
        batch_limit=reconciliation_batch_limit,
    )
    return ProductionRuntime(
        checkpoint=checkpoint,
        workflow_execution=workflow_execution,
        schedule_run_execution=schedule,
        redrive_workflow_handoffs=redrive,
        workflow_handoff_reconciliation_loop=loop,
    )
