from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import pytest
from tests.support.fakes import FakeWorkflowRuntime, WorkflowFailure

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import OpenRunRecord, QueryService, RunExecutionContext
from google_work_agent.ports import (
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)


@dataclass
class _QueryStub:
    status: str

    def list_open_runs(self) -> tuple[OpenRunRecord, ...]:
        return (
            OpenRunRecord(
                run_id="run-1",
                workflow_key="thread-1",
                status=self.status,
                version=3,
            ),
        )

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext:
        assert run_id == "run-1"
        return RunExecutionContext(
            run_id=run_id,
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            status=self.status,
            version=3,
            request_text="Recover the open run.",
            selected_resource_ids=(),
        )


@pytest.mark.parametrize(
    "status",
    ["WAITING_CONFIRMATION", "WAITING_APPROVAL", "VERIFYING", "RECOVERY_REQUIRED"],
)
def test_startup_reconciles_every_recoverable_open_run(status: str) -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="thread-1",
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": status},
        )
    )
    coordinator = LocalRunCoordinator(
        query_service=_QueryStub(status),  # type: ignore[arg-type]
        unit_of_work_factory=lambda: None,  # type: ignore[arg-type,return-value]
        workflow_runtime=runtime,
        event_publisher=InMemoryRunEventPublisher(
            service_instance_id="service-1",
            capacity_per_run=8,
        ),
        now_ms=lambda: 1000,
        api_contract_version="1",
    )

    coordinator.start()
    deadline = time.time() + 1
    while not runtime.call_log and time.time() < deadline:
        time.sleep(0.01)
    coordinator.stop()

    assert len(runtime.call_log) == 1
    assert runtime.call_log[0].operation == "recover_open_run"
    assert runtime.call_log[0].payload == {"domain_status": status, "domain_version": 3}


def test_workflow_outcome_failed_persists_run_status_not_only_an_sse_event(
    tmp_path: Path,
) -> None:
    """A FAILED WorkflowOutcome must leave the Domain Store holding FAILED.

    Previously ``_handle_result`` only published an "error" SSE event for
    this outcome; the run's persisted status stayed CREATED forever, so
    polling ``GET /runs/{id}`` (what the UI actually does) never saw the
    failure -- only a live SSE subscriber would.
    """

    database_path = tmp_path / "coordinator.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-1', 'user@example.com', 'User', 1);"
        )
        connection.execute(
            "INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) "
            "VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);"
        )
    finally:
        connection.close()

    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(database_path=database_path, runtime_status_provider=None)  # type: ignore[arg-type]

    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="thread-1",
            outcome=WorkflowOutcome.FAILED,
            payload={"safe_error_code": "PROMPT_NOT_ACTIVE"},
        )
    )
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=InMemoryRunEventPublisher(
            service_instance_id="service-1",
            capacity_per_run=8,
        ),
        now_ms=lambda: 2000,
        api_contract_version="1",
    )
    # Start the coordinator against an empty run table (its own startup
    # reconciliation sweep would otherwise enqueue "run-1" as a "recover"
    # item and consume the queued result before enqueue_start below ever
    # gets a chance to run it through the real "start" path).
    coordinator.start()

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()

    coordinator.enqueue_start(run_id="run-1", request_id="request-1", command_id="command-1")
    deadline = time.time() + 2
    while not runtime.call_log and time.time() < deadline:
        time.sleep(0.01)
    coordinator.stop()

    assert len(runtime.call_log) == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("FAILED", 2000)


def test_workflow_runtime_raising_persists_run_status_not_only_an_sse_event(
    tmp_path: Path,
) -> None:
    """A raising workflow_runtime call (e.g. an unrepaired schema-invalid
    structured LLM output) must still leave the Domain Store holding FAILED.

    Distinct from test_workflow_outcome_failed_persists_run_status_not_only_an_sse_event
    above: that test covers workflow_runtime returning WorkflowOutcome.FAILED
    cleanly. This covers workflow_runtime.start() raising instead of
    returning -- previously caught only by _worker_loop's outer try/except,
    which had no run version in scope and only published a transient SSE
    event, leaving the run non-terminal (e.g. ANALYZING) forever: the UI
    polls GET /runs/{id} rather than SSE, so it never saw the failure, and
    every later run was blocked by the has_active_runs() guard.
    """

    database_path = tmp_path / "coordinator-raise.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-1', 'user@example.com', 'User', 1);"
        )
        connection.execute(
            "INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) "
            "VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);"
        )
    finally:
        connection.close()

    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(database_path=database_path, runtime_status_provider=None)  # type: ignore[arg-type]

    runtime = FakeWorkflowRuntime()
    runtime.queue_failure(WorkflowFailure(message="structured output did not satisfy schema"))
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=InMemoryRunEventPublisher(
            service_instance_id="service-1",
            capacity_per_run=8,
        ),
        now_ms=lambda: 3000,
        api_contract_version="1",
    )
    coordinator.start()

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()

    coordinator.enqueue_start(run_id="run-1", request_id="request-1", command_id="command-1")
    deadline = time.time() + 2
    while not runtime.call_log and time.time() < deadline:
        time.sleep(0.01)
    coordinator.stop()

    assert len(runtime.call_log) == 1
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("FAILED", 3000)


class _VersionAdvancingThenFailingRuntime:
    """Bumps the run's domain version (simulating a real graph committing an
    internal transition, e.g. ANALYZING -> RETRIEVING) before raising --
    reproducing the case where expected_version, captured before dispatch,
    is stale by the time the exception handler tries to persist FAILED.
    """

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self.call_log: list[str] = []

    def _advance_version(self, run_id: str) -> None:
        connection = connect_sqlite(self._database_path)
        try:
            connection.execute(
                "UPDATE runs SET status = 'RETRIEVING', version = version + 1 WHERE id = ?;",
                (run_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        self.call_log.append("start")
        self._advance_version(request.run_id)
        raise RuntimeError("structured output did not satisfy schema")

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        raise NotImplementedError

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        raise NotImplementedError

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        raise NotImplementedError

    def close(self) -> None:
        return None


def test_workflow_runtime_raising_after_internal_transition_still_persists_failed(
    tmp_path: Path,
) -> None:
    """A run that advances (e.g. ANALYZING -> RETRIEVING) before its later
    node raises must still end up FAILED, not silently stuck at the
    intermediate status. Using the stale pre-dispatch expected_version for
    fail_run would hit VERSION_CONFLICT and no-op instead of applying.
    """

    database_path = tmp_path / "coordinator-stale-version.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-1', 'user@example.com', 'User', 1);"
        )
        connection.execute(
            "INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) "
            "VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);"
        )
    finally:
        connection.close()

    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    query_service = QueryService(database_path=database_path, runtime_status_provider=None)  # type: ignore[arg-type]

    runtime = _VersionAdvancingThenFailingRuntime(database_path)
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,  # type: ignore[arg-type]
        event_publisher=InMemoryRunEventPublisher(
            service_instance_id="service-1",
            capacity_per_run=8,
        ),
        now_ms=lambda: 4000,
        api_contract_version="1",
    )
    coordinator.start()

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()

    coordinator.enqueue_start(run_id="run-1", request_id="request-1", command_id="command-1")
    deadline = time.time() + 2
    while not runtime.call_log and time.time() < deadline:
        time.sleep(0.01)
    # Give the coordinator's exception handler a moment to run past the
    # raise before asserting on the persisted status.
    deadline = time.time() + 2
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status FROM runs WHERE id = 'run-1';"
        ).fetchone()
        while row is not None and row[0] != "FAILED" and time.time() < deadline:
            time.sleep(0.01)
            row = connection.execute(
                "SELECT status FROM runs WHERE id = 'run-1';"
            ).fetchone()
    finally:
        connection.close()
    coordinator.stop()

    assert runtime.call_log == ["start"]
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
    finally:
        connection.close()
    assert tuple(row) == ("FAILED", 4000)
