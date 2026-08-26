import time
from pathlib import Path

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClockPort, FakeWorkflowRuntime
from tests.support.workflow_admission import build_test_admission_callbacks

from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import build_production_runtime
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.security.access_guard import LocalApiAccessGuard
from google_work_agent.api.security.bootstrap import InMemoryBootstrapGrantStore
from google_work_agent.api.security.sessions import InMemoryLocalSessionManager
from google_work_agent.application.queries import QueryService
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationHandler,
)
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
)
from google_work_agent.application.use_cases.conversation.list_conversations import (
    ListConversationsHandler,
)
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

    clock = FakeClockPort(1000)
    runtime = FakeWorkflowRuntime()
    publisher = InMemorySseEventBuffer(service_instance_id="svc-test", capacity_per_run=8)
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
    id_generator = DeterministicUUID(prefix="req")

    checkpoint, materialize, invoke = build_test_admission_callbacks(
        checkpoint_path=tmp_path / "checkpoints.db",
        query_service=query_service,
        unit_of_work_factory=unit_of_work_factory,
        workflow_runtime=runtime,
        event_publisher=publisher,
        now_ms=clock.now_ms,
    )

    production_runtime = build_production_runtime(
        unit_of_work_factory=unit_of_work_factory,
        id_factory=id_generator.next_id,
        checkpoint=checkpoint,
        materialize_admission_checkpoint=materialize,
        invoke_semantic_owner=invoke,
        resume_target_registry=ResumeTargetRegistry(
            node_registry=NodeRegistry(graph_version=RESUME_CONTRACT_VERSION),
            graph_version=RESUME_CONTRACT_VERSION,
        ),
        now_ms=clock.now_ms,
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
        create_conversation_handler=CreateConversationHandler(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=clock.now_ms,
        ),
        list_conversations_handler=ListConversationsHandler(
            unit_of_work_factory=unit_of_work_factory,
        ),
        get_conversation_history_handler=GetConversationHistoryHandler(
            unit_of_work_factory=unit_of_work_factory,
        ),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        schedule_run_execution=production_runtime.schedule_run_execution,
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
        id_generator=id_generator,
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
                "request_text": "hello",
                "entry_mode": "AGENT_SEARCH",
                "selected_resource_handles": [],
                "requested_mode": "AUTO",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert start_response.status_code == 202
        run_id = start_response.json()["run_id"]
        workflow_key = start_response.json()["workflow_key"]
        runtime.queue_result(
            WorkflowInvocationResult(
                run_id=run_id,
                workflow_key=workflow_key,
                outcome=WorkflowOutcome.ACCEPTED,
                payload={"phase": "started"},
            )
        )

        deadline = time.time() + 2
        while time.time() < deadline and not publisher.replay(run_id=run_id, after_event_id=None):
            time.sleep(0.01)

        assert runtime.call_log
        assert runtime.call_log[0].operation == "start"
        replayed = publisher.replay(run_id=run_id, after_event_id=None)
        assert replayed
        assert replayed[0].event_type == "run_status"

        snapshot = client.get(f"/api/v1/runs/{run_id}", headers=headers)
        assert snapshot.status_code == 200
        assert snapshot.json()["snapshot"]["run_id"] == run_id

        with client.stream(
            "GET",
            f"/api/v1/runs/{run_id}/events",
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
