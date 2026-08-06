"""Queued workflow runtime test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from google_work_agent.ports import WorkflowInvocationResult


@dataclass(frozen=True, slots=True)
class WorkflowCallRecord:
    """Recorded workflow runtime invocation."""

    operation: str
    run_id: str
    workflow_key: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class WorkflowFailure:
    """One queued workflow failure."""

    message: str


class FakeWorkflowRuntime:
    """Queue-driven workflow runtime fake with no LangGraph dependency."""

    def __init__(self) -> None:
        self._results: list[WorkflowInvocationResult] = []
        self._failures: list[WorkflowFailure] = []
        self._bindings: dict[str, str] = {}
        self.call_log: list[WorkflowCallRecord] = []

    def queue_result(self, result: WorkflowInvocationResult) -> None:
        """Queue one successful invocation result."""

        self._results.append(result)

    def queue_failure(self, failure: WorkflowFailure) -> None:
        """Queue one invocation failure."""

        self._failures.append(failure)

    def start(
        self, *, run_id: str, workflow_key: str, payload: dict[str, object]
    ) -> WorkflowInvocationResult:
        """Start one workflow invocation."""

        return self._invoke("start", run_id, workflow_key, payload)

    def resume(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, object],
    ) -> WorkflowInvocationResult:
        """Resume one workflow invocation."""

        return self._invoke("resume", run_id, workflow_key, payload)

    def request_cancel(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, object],
    ) -> WorkflowInvocationResult:
        """Request one workflow cancellation."""

        return self._invoke("request_cancel", run_id, workflow_key, payload)

    def recover_open_run(
        self,
        *,
        run_id: str,
        workflow_key: str,
        payload: dict[str, object],
    ) -> WorkflowInvocationResult:
        """Recover one workflow run."""

        return self._invoke("recover_open_run", run_id, workflow_key, payload)

    def _invoke(
        self,
        operation: str,
        run_id: str,
        workflow_key: str,
        payload: dict[str, object],
    ) -> WorkflowInvocationResult:
        bound_workflow_key = self._bindings.get(run_id)
        if bound_workflow_key is None:
            self._bindings[run_id] = workflow_key
        elif bound_workflow_key != workflow_key:
            raise RuntimeError(
                f"run_id {run_id} is already bound to workflow_key {bound_workflow_key}"
            )

        self.call_log.append(
            WorkflowCallRecord(
                operation=operation,
                run_id=run_id,
                workflow_key=workflow_key,
                payload=deepcopy(payload),
            )
        )
        if self._failures:
            failure = self._failures.pop(0)
            raise RuntimeError(failure.message)
        if not self._results:
            raise RuntimeError("no queued workflow result available")
        result = self._results.pop(0)
        if result.run_id != run_id or result.workflow_key != workflow_key:
            raise RuntimeError("queued workflow result does not match invocation binding")
        return WorkflowInvocationResult(
            run_id=result.run_id,
            workflow_key=result.workflow_key,
            payload=deepcopy(result.payload),
        )
