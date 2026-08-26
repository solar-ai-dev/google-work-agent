"""Tests for the explicitly deferred LocalRunCoordinator control flows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Event

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import OpenRunRecord, RunExecutionContext
from google_work_agent.application.write_actions import WriteRunResponse
from google_work_agent.ports import (
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


@dataclass
class _MutableQueryStub:
    status: str = "EXECUTING"

    def list_open_runs(self) -> tuple[OpenRunRecord, ...]:
        return ()

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext:
        return RunExecutionContext(
            run_id=run_id,
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            status=self.status,
            version=4,
            request_text="Execute the approved plan.",
            selected_resource_ids=(),
        )


class _BlockingRuntime:
    def __init__(self) -> None:
        self.resume_entered = Event()
        self.release_resume = Event()
        self.call_log: list[str] = []

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        raise NotImplementedError

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        self.call_log.append("resume")
        self.resume_entered.set()
        assert self.release_resume.wait(timeout=2)
        return WorkflowInvocationResult(
            request.run_id,
            request.workflow_key,
            WorkflowOutcome.ACCEPTED,
            {"phase": "ACTION_EXECUTION"},
        )

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        self.call_log.append("request_cancel")
        return WorkflowInvocationResult(
            request.run_id,
            request.workflow_key,
            WorkflowOutcome.ACCEPTED,
            {"phase": "cancel_requested"},
        )

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        self.call_log.append("recover_open_run")
        return WorkflowInvocationResult(
            request.run_id, request.workflow_key, WorkflowOutcome.ACCEPTED, {}
        )

    def close(self) -> None:
        return None


def test_running_run_receives_cancel_signal_without_duplicate_graph_invocation() -> None:
    query = _MutableQueryStub()
    runtime = _BlockingRuntime()
    coordinator = _coordinator(query, runtime)
    coordinator.start()
    coordinator.enqueue_resume(
        run_id="run-1",
        request_id="request-1",
        command_id="command-1",
        resume_kind="SAFE_CHECKPOINT_RESUME",
        resume_payload={},
    )
    assert runtime.resume_entered.wait(timeout=1)

    query.status = "CANCEL_REQUESTED"
    coordinator.request_cancel(
        run_id="run-1",
        request_id="request-cancel",
        reason_code="user_requested",
    )
    runtime.release_resume.set()
    _wait_until(lambda: len(runtime.call_log) >= 2)
    coordinator.stop()

    assert runtime.call_log == ["resume", "request_cancel"]


@dataclass
class _CancellationContinuationQuery(_MutableQueryStub):
    status: str = "CANCEL_REQUESTED"
    version: int = 5

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext:
        context = super().get_run_execution_context(run_id)
        return RunExecutionContext(
            run_id=context.run_id,
            conversation_id=context.conversation_id,
            workflow_key=context.workflow_key,
            entry_mode=context.entry_mode,
            requested_mode=context.requested_mode,
            status=self.status,
            version=self.version,
            request_text=context.request_text,
            selected_resource_ids=context.selected_resource_ids,
        )

    def has_cancel_intent(self, run_id: str) -> bool:
        return run_id == "run-1"


class _RecoveryRuntime(_BlockingRuntime):
    def __init__(self, query: _CancellationContinuationQuery) -> None:
        super().__init__()
        self._query = query

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        self.call_log.append("recover_open_run")
        self._query.status = "VERIFYING"
        self._query.version += 1
        return WorkflowInvocationResult(
            request.run_id,
            request.workflow_key,
            WorkflowOutcome.ACCEPTED,
            {"phase": "RECOVERY", "run_status": "VERIFYING"},
        )


def test_recovery_resolution_continues_existing_cancel_intent_to_cancelled() -> None:
    query = _CancellationContinuationQuery()
    runtime = _RecoveryRuntime(query)
    finalize_calls: list[str] = []

    def finalize_cancel(_command: object) -> WriteRunResponse:
        finalize_calls.append(query.status)
        if len(finalize_calls) == 1:
            query.status = "RECOVERY_REQUIRED"
            query.version += 1
            result_kind = "RECOVERY_REQUIRED"
            applied = False
        else:
            query.status = "CANCELLED"
            query.version += 1
            result_kind = "PARTIAL"
            applied = True
        return WriteRunResponse(
            applied=applied,
            result_code="RECOVERY_REQUIRED" if not applied else "TRANSITION_APPLIED",
            run_id="run-1",
            run_status=query.status,
            run_version=query.version,
            plan_id="plan-1",
            plan_status="ACTIVE" if not applied else "CANCELLED",
            result_kind=result_kind,
        )

    ids = iter(("finalize-1", "finalize-2"))
    publisher = InMemoryRunEventPublisher(service_instance_id="service-1", capacity_per_run=8)
    coordinator = _coordinator(
        query,
        runtime,
        publisher=publisher,
        finalize_cancel_service=finalize_cancel,
        id_factory=lambda: next(ids),
    )
    coordinator.start()
    coordinator.request_cancel(
        run_id="run-1",
        request_id="request-cancel",
        reason_code="user_requested",
    )
    _wait_until(lambda: query.status == "CANCELLED")
    coordinator.stop()

    assert runtime.call_log == ["request_cancel", "recover_open_run"]
    assert finalize_calls == ["CANCEL_REQUESTED", "VERIFYING"]
    events = publisher.replay(run_id="run-1", after_event_id=None)
    assert any(
        event.event_type == "completed" and event.payload.get("result_kind") == "PARTIAL"
        for event in events
    )


def _coordinator(
    query: _MutableQueryStub,
    runtime: _BlockingRuntime,
    *,
    publisher: InMemoryRunEventPublisher | None = None,
    finalize_cancel_service=None,
    id_factory=None,
) -> LocalRunCoordinator:
    return LocalRunCoordinator(
        query_service=query,  # type: ignore[arg-type]
        unit_of_work_factory=lambda: None,  # type: ignore[arg-type,return-value]
        workflow_runtime=runtime,
        event_publisher=publisher
        or InMemoryRunEventPublisher(service_instance_id="service-1", capacity_per_run=8),
        now_ms=lambda: 6000,
        api_contract_version="1",
        finalize_cancel_service=finalize_cancel_service,
        id_factory=id_factory,
    )


def _wait_until(predicate) -> None:
    deadline = time.time() + 1
    while not predicate() and time.time() < deadline:
        time.sleep(0.01)
