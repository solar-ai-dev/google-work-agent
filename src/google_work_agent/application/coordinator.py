"""Local run coordinator decoupling HTTP from workflow execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, Lock, Thread

from google_work_agent.application.projections import build_projection_event
from google_work_agent.application.queries import QueryService
from google_work_agent.domain import RunStatus
from google_work_agent.ports import (
    PendingProjectionEvent,
    RunEventPublisher,
    UnitOfWork,
    WorkflowCancelRequest,
    WorkflowCorrelationContext,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowRuntime,
    WorkflowStartRequest,
)


@dataclass(frozen=True, slots=True)
class QueueBusyError(RuntimeError):
    """Raised when the bounded coordinator queue is full."""

    message: str = "local run queue is full"


@dataclass(frozen=True, slots=True)
class _QueueItem:
    kind: str
    run_id: str
    request_id: str
    command_id: str | None
    resume_kind: str | None = None
    resume_payload: dict[str, object] | None = None
    reason_code: str | None = None


class LocalRunCoordinator:
    """Single-worker in-memory queue for local workflow invocations."""

    def __init__(
        self,
        *,
        query_service: QueryService,
        unit_of_work_factory: Callable[[], UnitOfWork],
        workflow_runtime: WorkflowRuntime,
        event_publisher: RunEventPublisher,
        now_ms: Callable[[], int],
        api_contract_version: str,
        capacity: int = 32,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._query_service = query_service
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_runtime = workflow_runtime
        self._event_publisher = event_publisher
        self._now_ms = now_ms
        self._api_contract_version = api_contract_version
        self._queue: Queue[_QueueItem | None] = Queue(maxsize=capacity)
        self._queued_or_running: set[str] = set()
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._worker_loop, name="local-run-coordinator", daemon=True)
        self._thread.start()
        for run in self._query_service.list_open_runs():
            if run.status in {
                RunStatus.REAUTH_REQUIRED.value,
                RunStatus.COMPLETED.value,
                RunStatus.CANCELLED.value,
                RunStatus.FAILED.value,
            }:
                continue
            self._enqueue(
                _QueueItem(
                    kind="recover",
                    run_id=run.run_id,
                    request_id="startup-recovery",
                    command_id=None,
                )
            )

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return
        self._queue.put(None)
        thread.join(timeout=5)
        self._thread = None
        self._workflow_runtime.close()

    def enqueue_start(self, *, run_id: str, request_id: str, command_id: str) -> None:
        self._enqueue(
            _QueueItem(
                kind="start",
                run_id=run_id,
                request_id=request_id,
                command_id=command_id,
            )
        )

    def enqueue_resume(
        self,
        *,
        run_id: str,
        request_id: str,
        command_id: str | None,
        resume_kind: str,
        resume_payload: dict[str, object],
    ) -> None:
        self._enqueue(
            _QueueItem(
                kind="resume",
                run_id=run_id,
                request_id=request_id,
                command_id=command_id,
                resume_kind=resume_kind,
                resume_payload=resume_payload,
            )
        )

    def request_cancel(self, *, run_id: str, request_id: str, reason_code: str) -> None:
        self._enqueue(
            _QueueItem(
                kind="cancel",
                run_id=run_id,
                request_id=request_id,
                command_id=None,
                reason_code=reason_code,
            )
        )

    def _enqueue(self, item: _QueueItem) -> None:
        if self._stop_event.is_set():
            raise QueueBusyError("coordinator is shut down")
        with self._lock:
            if item.run_id in self._queued_or_running:
                return
            self._queued_or_running.add(item.run_id)
        try:
            self._queue.put_nowait(item)
        except Full as error:
            with self._lock:
                self._queued_or_running.discard(item.run_id)
            raise QueueBusyError() from error

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            item = self._queue.get()
            if item is None:
                break
            try:
                self._process_item(item)
            except Exception as error:
                self._publish(
                    build_projection_event(
                        run_id=item.run_id,
                        occurred_at_ms=self._now_ms(),
                        event_type="error",
                        payload={"error_code": "INTERNAL_ERROR", "message": str(error)[:200]},
                    )
                )
            finally:
                with self._lock:
                    self._queued_or_running.discard(item.run_id)

    def _process_item(self, item: _QueueItem) -> None:
        context = self._query_service.get_run_execution_context(item.run_id)
        if context is None:
            return
        if context.status in {
            RunStatus.COMPLETED.value,
            RunStatus.CANCELLED.value,
            RunStatus.FAILED.value,
        }:
            return
        correlation = WorkflowCorrelationContext(
            request_id=item.request_id,
            command_id=item.command_id,
            api_contract_version=self._api_contract_version,
        )
        if item.kind == "start":
            if context.status == RunStatus.RECOVERY_REQUIRED.value:
                return
            result = self._workflow_runtime.start(
                WorkflowStartRequest(
                    run_id=context.run_id,
                    conversation_id=context.conversation_id,
                    workflow_key=context.workflow_key,
                    entry_mode=context.entry_mode,
                    requested_mode=context.requested_mode,
                    request_text=context.request_text,
                    selected_resource_ids=context.selected_resource_ids,
                    correlation=correlation,
                    selected_resources=context.selected_resources,
                )
            )
        elif item.kind == "resume":
            result = self._workflow_runtime.resume(
                WorkflowResumeRequest(
                    run_id=context.run_id,
                    workflow_key=context.workflow_key,
                    resume_kind=item.resume_kind or "manual",
                    resume_payload=item.resume_payload or {},
                    correlation=correlation,
                )
            )
        elif item.kind == "cancel":
            result = self._workflow_runtime.request_cancel(
                WorkflowCancelRequest(
                    run_id=context.run_id,
                    workflow_key=context.workflow_key,
                    reason_code=item.reason_code or "user_requested",
                )
            )
        else:
            result = self._workflow_runtime.recover_open_run(
                WorkflowRecoveryRequest(
                    run_id=context.run_id,
                    workflow_key=context.workflow_key,
                    domain_status=context.status,
                    domain_version=context.version,
                    correlation=correlation,
                )
            )
        self._handle_result(context.run_id, result.outcome, result.payload)

    def _handle_result(
        self,
        run_id: str,
        outcome: WorkflowOutcome,
        payload: dict[str, object],
    ) -> None:
        if outcome in {
            WorkflowOutcome.CHECKPOINT_MISSING,
            WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
        }:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.runs.set_recovery_required(run_id, finished_at_ms=None)
                unit_of_work.commit()
            self._publish(
                build_projection_event(
                    run_id=run_id,
                    occurred_at_ms=self._now_ms(),
                    event_type="recovery_required",
                    payload={"outcome": outcome.value},
                )
            )
            return
        event_type = {
            WorkflowOutcome.ACCEPTED: _accepted_event_type(payload),
            WorkflowOutcome.ALREADY_RUNNING: "phase_changed",
            WorkflowOutcome.COMPLETED: "completed",
            WorkflowOutcome.RECOVERY_REQUIRED: "recovery_required",
            WorkflowOutcome.FAILED: "error",
        }[outcome]
        self._publish(
            build_projection_event(
                run_id=run_id,
                occurred_at_ms=self._now_ms(),
                event_type=event_type,
                payload={"outcome": outcome.value, **payload},
            )
        )

    def _publish(self, event: PendingProjectionEvent) -> None:
        try:
            self._event_publisher.publish(event)
        except Exception:
            return


def _accepted_event_type(payload: dict[str, object]) -> str:
    interrupt_payload = payload.get("user_interrupt")
    if isinstance(interrupt_payload, dict):
        interrupt_kind = interrupt_payload.get("interrupt_kind")
        if interrupt_kind == "CONFIRMATION":
            return "confirmation_required"
        if interrupt_kind == "APPROVAL":
            return "approval_required"
    phase = payload.get("phase")
    if phase == "WAITING_CONFIRMATION":
        return "confirmation_required"
    if phase == "WAITING_APPROVAL":
        return "approval_required"
    return "run_status"
