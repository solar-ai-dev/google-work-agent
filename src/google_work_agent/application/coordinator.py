"""Local run coordinator decoupling HTTP from workflow execution."""

from __future__ import annotations

import traceback
from collections.abc import Callable
from dataclasses import dataclass
from queue import Full, Queue
from threading import Event, Lock, Thread

from google_work_agent.application.coordinator_outcomes import (
    RunOutcomeHandler,
)
from google_work_agent.application.projections import build_projection_event
from google_work_agent.application.queries import QueryService, RunExecutionContext
from google_work_agent.application.write_actions import (
    FinalizeRunCancellationCommand,
    WriteRunResponse,
)
from google_work_agent.domain import RunStatus, calculate_canonical_json_hash
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
        finalize_cancel_service: Callable[[FinalizeRunCancellationCommand], WriteRunResponse]
        | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._query_service = query_service
        self._unit_of_work_factory = unit_of_work_factory
        self._workflow_runtime = workflow_runtime
        self._event_publisher = event_publisher
        self._now_ms = now_ms
        self._api_contract_version = api_contract_version
        self._finalize_cancel_service = finalize_cancel_service
        self._id_factory = id_factory
        self._queue: Queue[_QueueItem | None] = Queue(maxsize=capacity)
        self._queued_or_running: set[str] = set()
        self._reserved: set[str] = set()
        self._pending_items: dict[str, _QueueItem] = {}
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._outcomes = RunOutcomeHandler(
            unit_of_work_factory=unit_of_work_factory,
            event_publisher=event_publisher,
            now_ms=now_ms,
        )

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

    def reserve_start(self, *, run_id: str) -> bool:
        """Atomically claim admission for run_id before its Domain CREATED
        row commits, so a full/stopped queue can never leave that row
        behind with nothing to pick it up.

        The admission check and the reservation record are one atomic
        operation under the shared lock, and every other producer
        (_enqueue, request_cancel) checks the same
        ``qsize() + len(_reserved) < capacity`` invariant before claiming a
        slot for itself -- so a reservation held here can never be starved
        by another producer enqueuing in the window before confirm_start
        runs. Pair a True result with confirm_start on success, or
        release_reservation if the paired attempt does not end up
        creating/enqueuing the run after all.
        """
        if self._stop_event.is_set():
            return False
        with self._lock:
            if run_id in self._queued_or_running:
                return False
            if self._queue.qsize() + len(self._reserved) >= self._queue.maxsize:
                return False
            self._queued_or_running.add(run_id)
            self._reserved.add(run_id)
            return True

    def confirm_start(self, *, run_id: str, request_id: str, command_id: str) -> None:
        """Atomically convert a reserve_start() admission into a real queue item.

        Releasing the reservation and performing the actual put happen
        under the same lock acquisition, so no other producer can observe
        an intermediate state where the slot is neither reserved nor
        occupied.
        """
        item = _QueueItem(kind="start", run_id=run_id, request_id=request_id, command_id=command_id)
        with self._lock:
            self._reserved.discard(run_id)
            try:
                self._queue.put_nowait(item)
            except Full as error:
                self._queued_or_running.discard(run_id)
                raise QueueBusyError() from error

    def release_reservation(self, *, run_id: str) -> None:
        """Release a reserve_start() admission that never reached confirm_start()."""
        with self._lock:
            self._reserved.discard(run_id)
            self._queued_or_running.discard(run_id)

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
        context = self._query_service.get_run_execution_context(run_id)
        if context is None or context.status in {
            RunStatus.COMPLETED.value,
            RunStatus.CANCELLED.value,
            RunStatus.FAILED.value,
        }:
            return
        signal_result = self._workflow_runtime.request_cancel(
            WorkflowCancelRequest(
                run_id=context.run_id,
                workflow_key=context.workflow_key,
                reason_code=reason_code,
            )
        )
        self._handle_result(
            run_id,
            signal_result.outcome,
            signal_result.payload,
            context.version,
        )
        item = _QueueItem(
            kind="cancel",
            run_id=run_id,
            request_id=request_id,
            command_id=None,
            reason_code=reason_code,
        )
        with self._lock:
            if run_id in self._queued_or_running:
                self._pending_items[run_id] = item
                return
            self._claim_and_put_locked(item)

    def _enqueue(self, item: _QueueItem) -> None:
        if self._stop_event.is_set():
            raise QueueBusyError("coordinator is shut down")
        with self._lock:
            if item.run_id in self._queued_or_running:
                pending = self._pending_items.get(item.run_id)
                if item.kind == "resume" and (pending is None or pending.kind != "cancel"):
                    self._pending_items[item.run_id] = item
                return
            self._claim_and_put_locked(item)

    def _claim_and_put_locked(self, item: _QueueItem) -> None:
        """Admit and physically enqueue item. Must be called while already
        holding self._lock, with item.run_id confirmed absent from
        _queued_or_running by the caller.

        This is the single shared capacity gate for every producer
        (_enqueue and request_cancel): admission is checked against actual
        queue occupancy plus any outstanding reserve_start() reservations,
        and the put happens in the same lock acquisition, so no other
        thread can observe or race the capacity decision in between.
        """
        if self._queue.qsize() + len(self._reserved) >= self._queue.maxsize:
            raise QueueBusyError()
        self._queued_or_running.add(item.run_id)
        try:
            self._queue.put_nowait(item)
        except Full as error:
            self._queued_or_running.discard(item.run_id)
            raise QueueBusyError() from error

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            item = self._queue.get()
            if item is None:
                break
            while item is not None:
                try:
                    self._process_item(item)
                except Exception as error:
                    # Last-resort net for failures _process_item itself could not
                    # attribute to a run (e.g. get_run_execution_context itself
                    # raising).
                    traceback.print_exc()
                    self._publish(
                        build_projection_event(
                            run_id=item.run_id,
                            occurred_at_ms=self._now_ms(),
                            event_type="error",
                            payload={
                                "error_code": "INTERNAL_ERROR",
                                "message": str(error)[:200],
                            },
                        )
                    )
                with self._lock:
                    pending_item = self._pending_items.pop(item.run_id, None)
                    if pending_item is None:
                        self._queued_or_running.discard(item.run_id)
                item = pending_item

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
        if item.kind == "cancel":
            self._continue_cancellation(item=item, recover_if_needed=True)
            return
        correlation = WorkflowCorrelationContext(
            request_id=item.request_id,
            command_id=item.command_id,
            api_contract_version=self._api_contract_version,
        )
        expected_version = context.version
        if item.kind == "start" and context.status == RunStatus.RECOVERY_REQUIRED.value:
            return
        if item.kind == "start":
            expected_version = self._ensure_analysis_started(context.run_id)
        try:
            if item.kind == "start":
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
        except Exception as error:
            # A raising workflow_runtime call (e.g. LLMInvocationError from
            # an unrepaired schema-invalid structured output) must still
            # move the run to a terminal domain state. Swallowing it here
            # and leaving the run non-terminal forever both hides the
            # failure from the UI (which polls GET /runs/{id}, not the
            # transient SSE stream) and permanently blocks every later run
            # via the has_active_runs() guard.
            #
            # expected_version was captured before workflow_runtime.start()
            # ran. The graph itself commits its own domain transitions
            # (e.g. CREATED -> ANALYZING -> RETRIEVING) as it progresses
            # through nodes, so by the time a later node raises, the run's
            # real current version has moved past expected_version --
            # calling fail_run with the stale value hits VERSION_CONFLICT
            # and silently no-ops (fail_run reports a conflict rather than
            # raising), leaving the run stuck exactly like before this
            # fix. Re-fetch the actual current version first.
            traceback.print_exc()
            current_context = self._query_service.get_run_execution_context(context.run_id)
            current_version = (
                current_context.version if current_context is not None else expected_version
            )
            self._handle_result(
                context.run_id,
                WorkflowOutcome.FAILED,
                {"error_code": "INTERNAL_ERROR", "message": str(error)[:200]},
                current_version,
            )
            return
        self._handle_result(context.run_id, result.outcome, result.payload, expected_version)
        if item.kind == "recover" and self._has_cancel_intent(context.run_id):
            self._continue_cancellation(item=item, recover_if_needed=False)

    def _continue_cancellation(self, *, item: _QueueItem, recover_if_needed: bool) -> None:
        if self._finalize_cancel_service is None or self._id_factory is None:
            return
        context = self._query_service.get_run_execution_context(item.run_id)
        if context is None or context.status in {
            RunStatus.COMPLETED.value,
            RunStatus.CANCELLED.value,
            RunStatus.FAILED.value,
        }:
            return

        if context.status == RunStatus.RECOVERY_REQUIRED.value:
            if not recover_if_needed:
                return
            self._recover_for_cancellation(item=item, context=context)
            self._continue_cancellation(item=item, recover_if_needed=False)
            return

        if context.status == RunStatus.VERIFYING.value and not self._has_cancel_intent(item.run_id):
            return
        if context.status not in {
            RunStatus.CANCEL_REQUESTED.value,
            RunStatus.VERIFYING.value,
        }:
            return
        response = self._finalize_cancel_service(
            FinalizeRunCancellationCommand(
                command_id=self._id_factory(),
                request_hash=calculate_canonical_json_hash(
                    {"kind": "finalize_cancel", "run_id": item.run_id}
                ),
                run_id=item.run_id,
                expected_run_version=context.version,
            )
        )
        self._publish_cancel_response(response)
        if response.applied and response.run_status == RunStatus.CANCELLED.value:
            self._workflow_runtime.discard_run_transients(item.run_id)
            return
        if response.run_status in {
            RunStatus.RECOVERY_REQUIRED.value,
            RunStatus.VERIFYING.value,
        }:
            updated_context = self._query_service.get_run_execution_context(item.run_id)
            if updated_context is None:
                return
            self._recover_for_cancellation(item=item, context=updated_context)
            self._continue_cancellation(item=item, recover_if_needed=False)

    def _recover_for_cancellation(self, *, item: _QueueItem, context: RunExecutionContext) -> None:
        run_context = context
        result = self._workflow_runtime.recover_open_run(
            WorkflowRecoveryRequest(
                run_id=run_context.run_id,
                workflow_key=run_context.workflow_key,
                domain_status=run_context.status,
                domain_version=run_context.version,
                correlation=WorkflowCorrelationContext(
                    request_id=item.request_id,
                    command_id=None,
                    api_contract_version=self._api_contract_version,
                ),
            )
        )
        self._handle_result(
            run_context.run_id,
            result.outcome,
            result.payload,
            run_context.version,
        )

    def _has_cancel_intent(self, run_id: str) -> bool:
        checker = getattr(self._query_service, "has_cancel_intent", None)
        return bool(checker is not None and checker(run_id))

    def _publish_cancel_response(self, response: WriteRunResponse) -> None:
        self._outcomes.publish_cancel_response(response)

    def _ensure_analysis_started(self, run_id: str) -> int:
        """Guarantee a run has left CREATED before any outcome is recorded against it.

        CREATED only ever transitions via START_ANALYSIS
        (domain/transitions.py); FAIL_RUN is valid only from
        ANALYZING/RETRIEVING/PLANNING. Every real graph node already performs
        this exact guarded transition as its own first action (see
        adapters/langgraph/runtime.py::_transition_run); placeholder runtimes
        such as ``_PromptInactiveWorkflowRuntime`` never touch the domain
        store at all, which is what let a FAILED outcome try -- and silently
        fail -- to persist against a run still sitting in CREATED.
        """
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(run_id)
            if run is None:
                raise LookupError(f"run not found: {run_id}")
            if run.status is not RunStatus.CREATED:
                return run.version
            result = unit_of_work.runs.start_analysis(
                run_id,
                expected_version=run.version,
                finished_at_ms=None,
            )
            if result.applied:
                unit_of_work.commit()
                return result.current_version
            return run.version

    def _handle_result(
        self,
        run_id: str,
        outcome: WorkflowOutcome,
        payload: dict[str, object],
        expected_version: int,
    ) -> None:
        self._outcomes.handle_result(run_id, outcome, payload, expected_version)

    def _publish(self, event: PendingProjectionEvent) -> None:
        self._outcomes.publish(event)
