"""Drive the canonical workflow-handoff reconciler while the service is alive."""

from __future__ import annotations

from threading import Event, Thread

from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
)


class WorkflowHandoffReconciliationLoop:
    def __init__(
        self,
        *,
        redrive: RedriveWorkflowHandoffsHandler,
        interval_seconds: float = 1.0,
        batch_limit: int = 32,
    ) -> None:
        if interval_seconds <= 0 or batch_limit < 1:
            raise ValueError("invalid reconciliation loop configuration")
        self._redrive = redrive
        self._interval_seconds = interval_seconds
        self._batch_limit = batch_limit
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(
            target=self._run,
            name="workflow-handoff-reconciliation",
            daemon=True,
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            while not self._stop.is_set():
                result = self._redrive(RedriveWorkflowHandoffsCommand(limit=self._batch_limit))
                if not result.has_more or result.progressed_count == 0:
                    break
            self._wake.wait(self._interval_seconds)
            self._wake.clear()
