"""Queued workflow runtime test double."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass

from google_work_agent.ports import (
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


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
        self._results.append(result)

    def queue_failure(self, failure: WorkflowFailure) -> None:
        self._failures.append(failure)

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        return self._invoke("start", request.run_id, request.workflow_key, asdict(request))

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        return self._invoke("resume", request.run_id, request.workflow_key, request.resume_payload)

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        return self._invoke(
            "request_cancel",
            request.run_id,
            request.workflow_key,
            {"reason_code": request.reason_code},
        )

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        return self._invoke(
            "recover_open_run",
            request.run_id,
            request.workflow_key,
            {"domain_status": request.domain_status, "domain_version": request.domain_version},
        )

    def close(self) -> None:
        return None

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
            outcome=result.outcome,
            payload=deepcopy(result.payload),
        )
