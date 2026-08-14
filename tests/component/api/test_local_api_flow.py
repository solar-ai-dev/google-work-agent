import time
from pathlib import Path

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock, FakeWorkflowRuntime

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.api import ApiContainer, create_app
from google_work_agent.api.security import (
    InMemoryBootstrapGrantStore,
    InMemoryLocalSessionManager,
    LocalApiAccessGuard,
)
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import QueryService
from google_work_agent.application.start_run import CreateConversationService, StartRunService
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    LauncherProbeDecision,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeSummary,
    WorkflowInvocationResult,
    WorkflowOutcome,
)


class _AllowGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(allowed=True)


def test_local_api_flow_creates_conversation_starts_run_and_replays_sse(tmp_path: Path) -> None:
    database_path = tmp_path / "api-flow.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
    finally:
        connection.close()

    clock = FakeClock(1000)
    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="workflow-1",
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": "started"},
        )
    )
    publisher = InMemoryRunEventPublisher(service_instance_id="svc-test", capacity_per_run=8)
    query_service = QueryService(
        database_path=database_path,
        connection_factory=connect_sqlite,
        runtime_status_provider=StaticRuntimeStatusProvider(
            RuntimeSummary(
                google="NOT_CONFIGURED",
                mcp="NOT_CONFIGURED",
                api_llm="NOT_CONFIGURED",
                ollama="NOT_AVAILABLE",
                deployment_profile="test",
                recovery_required_run_ids=(),
                open_run_ids=(),
            )
        ),
    )
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    coordinator = LocalRunCoordinator(
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=publisher,
        now_ms=clock.now_ms,
        api_contract_version="1",
        capacity=4,
    )
    bind_host = "127.0.0.1"
    bind_port = 8765
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="bootstrap-secret",
        service_instance_id="svc-test",
        now_ms=clock.now_ms(),
    )
    session_manager = InMemoryLocalSessionManager()
    container = ApiContainer(
        unit_of_work_factory=unit_of_work_factory,
        query_service=query_service,
        create_conversation_service=CreateConversationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        start_run_service=StartRunService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        approve_action_service=ApproveWriteActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        modify_action_service=lambda command: {
            "applied": False,
            "result_code": "STATE_CONFLICT",
            "action_id": command.action_id,
            "action_status": "UNKNOWN",
            "action_version": 0,
            "next_allowed_commands": (),
            "conflict_detail": "not seeded",
        },
        reject_action_service=lambda command: {
            "applied": False,
            "result_code": "STATE_CONFLICT",
            "action_id": command.action_id,
            "action_status": "UNKNOWN",
            "action_version": 0,
            "next_allowed_commands": (),
            "conflict_detail": "not seeded",
        },
        prepare_retry_service=PrepareWriteRetryService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        cancel_run_service=RequestRunCancellationService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        resume_run_service=lambda command: command,
        local_run_coordinator=coordinator,
        workflow_runtime=runtime,
        event_publisher=publisher,
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(
                state=ReadinessState.READY,
                checks=(
                    ReadinessCheckResult(name="sqlite_connection", state=ReadinessState.READY),
                ),
            )
        ),
        runtime_status_provider=query_service._runtime_status_provider,
        api_access_guard=LocalApiAccessGuard(
            expected_host=f"{bind_host}:{bind_port}",
            expected_origin=f"http://{bind_host}:{bind_port}",
            service_instance_id="svc-test",
            session_manager=session_manager,
            release_version="test",
            environment="test",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id="svc-test",
        local_bind_host=bind_host,
        local_bind_port=bind_port,
        bootstrap_grant_store=bootstrap_store,
        local_session_manager=session_manager,
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        client_address_resolver=lambda _request: "127.0.0.1",
    )

    headers = {
        "Origin": f"http://{bind_host}:{bind_port}",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with TestClient(create_app(container), base_url=f"http://{bind_host}:{bind_port}") as client:
        bootstrap_response = client.post(
            "/api/v1/session/bootstrap",
            json={
                "bootstrap_secret": "bootstrap-secret",
                "service_instance_id": "svc-test",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert bootstrap_response.status_code == 200
        assert "gwa_session" in bootstrap_response.headers["set-cookie"]

        create_response = client.post(
            "/api/v1/conversations",
            json={
                "command_id": "conversation-cmd-1",
                "conversation_id": "conversation-1",
                "account_id": "account-1",
                "title": "Inbox",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert create_response.status_code == 201

        start_response = client.post(
            "/api/v1/runs",
            json={
                "command_id": "run-cmd-1",
                "conversation_id": "conversation-1",
                "user_message_id": "message-1",
                "run_id": "run-1",
                "workflow_key": "workflow-1",
                "request_text": "hello",
                "entry_mode": "AGENT_SEARCH",
                "selected_resource_ids": [],
                "requested_mode": "AUTO",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert start_response.status_code == 202

        deadline = time.time() + 2
        while time.time() < deadline and not runtime.call_log:
            time.sleep(0.01)

        assert runtime.call_log
        assert runtime.call_log[0].operation == "start"
        replayed = publisher.replay(run_id="run-1", after_event_id=None)
        assert replayed
        assert replayed[0].event_type == "run_status"

        snapshot = client.get("/api/v1/runs/run-1", headers=headers)
        assert snapshot.status_code == 200
        assert snapshot.json()["snapshot"]["run_id"] == "run-1"

        with client.stream(
            "GET",
            "/api/v1/runs/run-1/events",
            headers={**headers, "Last-Event-ID": "other-service:1"},
        ) as stream:
            lines = [line for line in stream.iter_lines() if line]

        assert any(line.startswith("id: svc-test:") for line in lines)
        assert any(line == "event: snapshot_required" for line in lines)

        blocked = client.post(
            "/api/v1/conversations",
            json={
                "command_id": "conversation-cmd-2",
                "conversation_id": "conversation-2",
                "account_id": "account-1",
                "title": "Blocked",
                "api_contract_version": "1",
            },
            headers={**headers, "Origin": "http://malicious.example"},
        )
        assert blocked.status_code == 403
