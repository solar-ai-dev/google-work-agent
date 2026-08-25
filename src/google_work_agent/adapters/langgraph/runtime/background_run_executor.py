"""Single process-local worker for persisted workflow execution admissions."""

from __future__ import annotations

import time
from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionSubmissionV2,
)


class BackgroundRunExecutorAdapter:
    """Accept only durable admissions and execute each admission at most once."""

    def __init__(
        self,
        *,
        execute_admission: Callable[[WorkflowExecutionAdmissionV1], None],
        capacity: int = 32,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._execute_admission = execute_admission
        self._queue: Queue[WorkflowExecutionAdmissionV1] = Queue(maxsize=capacity)
        self._accepted_admission_ids: set[str] = set()
        self._active_run_admissions: dict[str, str] = {}
        self._lock = Lock()
        self._stop = Event()
        self._thread = Thread(target=self._run, name="background-run-executor", daemon=True)
        self._thread.start()

    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1:
        admission = submission.admission
        with self._lock:
            if self._stop.is_set():
                return _result(False, "SHUTTING_DOWN")
            if admission.admission_id in self._accepted_admission_ids:
                return _result(True, "ACCEPTED")
            active = self._active_run_admissions.get(admission.effective_binding.run_id)
            if active is not None and active != admission.admission_id:
                return _result(False, "ALREADY_RUNNING")
            try:
                self._queue.put_nowait(admission)
            except Full:
                return _result(False, "ALREADY_RUNNING")
            self._accepted_admission_ids.add(admission.admission_id)
            self._active_run_admissions[admission.effective_binding.run_id] = admission.admission_id
        return _result(True, "ACCEPTED")

    def begin_shutdown(self) -> None:
        self._stop.set()

    def await_drained(self, deadline_ms: int) -> bool:
        deadline = time.monotonic() + max(0, deadline_ms) / 1000
        while time.monotonic() <= deadline:
            with self._lock:
                if self._queue.unfinished_tasks == 0 and not self._active_run_admissions:
                    return True
            time.sleep(0.01)
        return False

    def close(self) -> None:
        self.begin_shutdown()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.is_set() or self._queue.unfinished_tasks:
            try:
                admission = self._queue.get(timeout=0.05)
            except Empty:
                continue
            try:
                self._execute_admission(admission)
            finally:
                with self._lock:
                    self._active_run_admissions.pop(admission.effective_binding.run_id, None)
                self._queue.task_done()


def _result(accepted: bool, reason_code: str) -> RunExecutionAcceptedV1:
    return RunExecutionAcceptedV1(
        schema_version=1,
        accepted=accepted,
        reason_code=reason_code,  # type: ignore[arg-type]
    )
