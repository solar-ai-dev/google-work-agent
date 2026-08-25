"""Single concrete production composition authority."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.system.workflow_handoff_reconciliation_loop import (
    WorkflowHandoffReconciliationLoop,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    EffectiveBindingResolver,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import WorkflowExecutionAdmissionV1


@dataclass(frozen=True, slots=True)
class ProductionRuntime:
    workflow_execution: BackgroundRunExecutorAdapter
    schedule_run_execution: ScheduleRunExecutionHandler
    redrive_workflow_handoffs: RedriveWorkflowHandoffsHandler
    workflow_handoff_reconciliation_loop: WorkflowHandoffReconciliationLoop


def build_production_runtime(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    id_factory: Callable[[], str],
    execute_admission: Callable[[WorkflowExecutionAdmissionV1], None],
    effective_binding_resolver: EffectiveBindingResolver | None = None,
    reconciliation_interval_seconds: float = 1.0,
    reconciliation_batch_limit: int = 32,
) -> ProductionRuntime:
    """Bind the durable handoff slice exactly once at the service boundary."""
    workflow_execution = BackgroundRunExecutorAdapter(execute_admission=execute_admission)
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=unit_of_work_factory,
        workflow_execution=workflow_execution,
        id_factory=id_factory,
        effective_binding_resolver=effective_binding_resolver,
    )
    redrive = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=unit_of_work_factory,
        schedule_run_execution=schedule,
    )
    loop = WorkflowHandoffReconciliationLoop(
        redrive=redrive,
        interval_seconds=reconciliation_interval_seconds,
        batch_limit=reconciliation_batch_limit,
    )
    return ProductionRuntime(
        workflow_execution=workflow_execution,
        schedule_run_execution=schedule,
        redrive_workflow_handoffs=redrive,
        workflow_handoff_reconciliation_loop=loop,
    )
