"""Single process-local worker for persisted workflow execution admissions."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import TypeGuard

from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffV1,
)

LOGGER = logging.getLogger(__name__)


class BackgroundRunExecutorAdapter:
    """Consume and settle persisted admissions before semantic owner invocation."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        materialize_admission_checkpoint: Callable[
            [WorkflowExecutionAdmissionV1, WorkflowHandoffV1], GraphCheckpointEnvelopeV1
        ],
        invoke_semantic_owner: Callable[[WorkflowExecutionAdmissionV1, WorkflowHandoffV1], None],
        release_active_lineage: Callable[[str, str, str, int], None],
        capacity: int = 32,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._materialize_admission_checkpoint = materialize_admission_checkpoint
        self._invoke_semantic_owner = invoke_semantic_owner
        self._release_active_lineage = release_active_lineage
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
                self._consume(admission)
            except Exception:
                LOGGER.exception(
                    "workflow admission consumption failed",
                    extra={
                        "admission_id": admission.admission_id,
                        "handoff_id": admission.handoff_id,
                        "run_id": admission.effective_binding.run_id,
                    },
                )
            finally:
                with self._lock:
                    self._active_run_admissions.pop(admission.effective_binding.run_id, None)
                self._queue.task_done()

    def _consume(self, admission: WorkflowExecutionAdmissionV1) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(admission.handoff_id)
            if not _is_exact_active_admission(handoff, admission):
                return

        checkpoint = self._prepare_admission_checkpoint(admission, handoff)

        with self._unit_of_work_factory() as unit_of_work:
            current = unit_of_work.workflow_handoffs.get(admission.handoff_id)
            if not _is_exact_active_admission(current, admission):
                return
            if admission.submission_kind == "NORMAL_HANDOFF":
                settlement = unit_of_work.workflow_handoffs.mark_consumed_and_clear_payload(
                    current.handoff_id,
                    current.version,
                    admission.admission_id,
                    checkpoint.checkpoint_id,
                    checkpoint.checkpoint_generation,
                )
            else:
                settlement = unit_of_work.workflow_handoffs.complete_recovery_admission(
                    current.handoff_id,
                    current.version,
                    admission.admission_id,
                    checkpoint.checkpoint_id,
                    checkpoint.checkpoint_generation,
                )
            unit_of_work.commit()

        if settlement.outcome != "SETTLED":
            self._release_active_lineage(
                checkpoint.run_id,
                checkpoint.langgraph_thread_id,
                handoff.handoff_id,
                handoff.run_sequence,
            )
            return
        self._invoke_semantic_owner(admission, handoff)
        self._release_active_lineage(
            checkpoint.run_id,
            checkpoint.langgraph_thread_id,
            handoff.handoff_id,
            handoff.run_sequence,
        )

    def _prepare_admission_checkpoint(
        self,
        admission: WorkflowExecutionAdmissionV1,
        handoff: WorkflowHandoffV1,
    ) -> GraphCheckpointEnvelopeV1:
        binding = admission.effective_binding
        latest = self._checkpoint_port.load_same_run_checkpoint(
            binding.run_id, binding.langgraph_thread_id
        )
        if latest is not None and latest.execution_admission_id == admission.admission_id:
            self._prove_control_materialized(latest, admission, handoff)
            return latest
        if binding.execution_kind == "START":
            checkpoint = self._materialize_admission_checkpoint(admission, handoff)
            if (
                checkpoint.execution_admission_id != admission.admission_id
                or checkpoint.active_handoff_id != handoff.handoff_id
                or checkpoint.active_handoff_run_sequence != handoff.run_sequence
            ):
                raise ValueError("materialized START checkpoint does not match admission")
            return checkpoint
        if binding.execution_kind == "RESUME" and (
            latest is None
            or latest.checkpoint_id != binding.checkpoint_id
            or latest.checkpoint_generation != binding.checkpoint_generation
            or latest.registered_resume_target != binding.resume_target
        ):
            raise ValueError("persisted RESUME admission does not match latest checkpoint")
        if latest is None:
            raise ValueError("RESUME admission requires a native checkpoint")
        checkpoint = replace(
            latest,
            registered_resume_target=binding.resume_target,
            execution_admission_id=admission.admission_id,
            active_handoff_id=handoff.handoff_id,
            active_handoff_run_sequence=handoff.run_sequence,
        )
        self._checkpoint_port.store_same_run_checkpoint(checkpoint)
        self._checkpoint_port.flush()
        if admission.submission_kind == "NORMAL_HANDOFF":
            checkpoint = self._materialize_admission_checkpoint(admission, handoff)
        if admission.submission_kind == "NORMAL_HANDOFF":
            checkpoint = replace(checkpoint, applied_handoff_id=handoff.handoff_id)
            self._checkpoint_port.store_same_run_checkpoint(checkpoint)
            self._checkpoint_port.flush()
        self._prove_control_materialized(checkpoint, admission, handoff)
        return checkpoint

    def _prove_control_materialized(
        self,
        checkpoint: GraphCheckpointEnvelopeV1,
        admission: WorkflowExecutionAdmissionV1,
        handoff: WorkflowHandoffV1,
    ) -> None:
        if admission.submission_kind != "NORMAL_HANDOFF":
            return
        if checkpoint.applied_handoff_id != handoff.handoff_id:
            raise ValueError("checkpoint does not contain applied handoff evidence")


def _result(accepted: bool, reason_code: str) -> RunExecutionAcceptedV1:
    return RunExecutionAcceptedV1(
        schema_version=1,
        accepted=accepted,
        reason_code=reason_code,  # type: ignore[arg-type]
    )


def _is_exact_active_admission(
    handoff: WorkflowHandoffV1 | None,
    admission: WorkflowExecutionAdmissionV1,
) -> TypeGuard[WorkflowHandoffV1]:
    return handoff is not None and handoff.execution_admission == admission
