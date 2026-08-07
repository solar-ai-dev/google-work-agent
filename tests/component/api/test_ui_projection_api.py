from pathlib import Path

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClock, FakeGoogleGateway, FakeWorkflowRuntime
from tests.support.fixtures import ProductFixtureSnapshotLoader

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
from google_work_agent.application.queries import QueryService
from google_work_agent.application.resource_queries import ResourceQueryService
from google_work_agent.application.start_run import CreateConversationService, StartRunService
from google_work_agent.application.write_actions import (
    ApproveWriteActionService,
    PrepareWriteRetryService,
    RequestRunCancellationService,
)
from google_work_agent.ports import (
    LauncherProbeDecision,
    ReadinessCheckResult,
    ReadinessReport,
    ReadinessState,
    RuntimeSummary,
)


def test_ui_projection_routes_expose_identity_resources_and_run_context(tmp_path: Path) -> None:
    database_path = tmp_path / "ui-projections.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )

    fixture_root = Path(__file__).resolve().parents[2] / "fixtures" / "product"
    snapshot = ProductFixtureSnapshotLoader(fixture_root).load_snapshot("manifest.json")
    gateway = FakeGoogleGateway(snapshot)
    clock = FakeClock(1_000)
    runtime = FakeWorkflowRuntime()
    publisher = InMemoryRunEventPublisher(service_instance_id="svc-ui", capacity_per_run=8)
    query_service = QueryService(
        database_path=database_path,
        runtime_status_provider=StaticRuntimeStatusProvider(
            RuntimeSummary(
                google="CONNECTED",
                mcp="READY",
                api_llm="NOT_CONFIGURED",
                ollama="NOT_AVAILABLE",
                deployment_profile="test",
                recovery_required_run_ids=(),
                open_run_ids=(),
            )
        ),
    )
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    bootstrap_store = InMemoryBootstrapGrantStore()
    bootstrap_store.provision(
        secret="bootstrap-secret",
        service_instance_id="svc-ui",
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
        local_run_coordinator=type(
            "CoordinatorStub",
            (),
            {
                "start": lambda self: None,
                "stop": lambda self: None,
                "enqueue_start": lambda self, **kwargs: None,
                "enqueue_resume": lambda self, **kwargs: None,
                "request_cancel": lambda self, **kwargs: None,
            },
        )(),
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
            expected_host="127.0.0.1:8770",
            expected_origin="http://127.0.0.1:8770",
            service_instance_id="svc-ui",
            session_manager=session_manager,
            release_version="test",
            environment="test",
            now_ms=clock.now_ms,
        ),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="test",
        environment="test",
        service_instance_id="svc-ui",
        local_bind_host="127.0.0.1",
        local_bind_port=8770,
        bootstrap_grant_store=bootstrap_store,
        local_session_manager=session_manager,
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        client_address_resolver=lambda _request: "127.0.0.1",
        resource_query_service=ResourceQueryService(gateway=gateway),
    )

    headers = {
        "Origin": "http://127.0.0.1:8770",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with TestClient(create_app(container), base_url="http://127.0.0.1:8770") as client:
        bootstrap = client.post(
            "/api/v1/session/bootstrap",
            json={
                "bootstrap_secret": "bootstrap-secret",
                "service_instance_id": "svc-ui",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert bootstrap.status_code == 200

        account = client.get("/api/v1/identity/google-account", headers=headers)
        assert account.status_code == 200
        assert account.json()["account"]["account_id"] == "account-1"

        gmail = client.get("/api/v1/resources/gmail?query=project&page_size=20", headers=headers)
        assert gmail.status_code == 200
        assert gmail.json()["items"][0]["resource_id"] == "thread-project"

        tasks = client.get("/api/v1/resources/tasks?page_size=20", headers=headers)
        assert tasks.status_code == 200
        assert tasks.json()["items"][0]["resource_type"] == "task_list"

        created = client.post(
            "/api/v1/conversations",
            json={
                "command_id": "conversation-cmd-1",
                "request_hash": "a" * 64,
                "conversation_id": "conversation-1",
                "account_id": "account-1",
                "title": "Inbox",
                "api_contract_version": "1",
            },
            headers=headers,
        )
        assert created.status_code == 201

        started = client.post(
            "/api/v1/runs",
            json={
                "command_id": "run-cmd-1",
                "request_hash": "b" * 64,
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
        assert started.status_code == 202

        latest_run = client.get("/api/v1/conversations/conversation-1/latest-run", headers=headers)
        assert latest_run.status_code == 200
        assert latest_run.json()["run"]["run_id"] == "run-1"

        context = client.get("/api/v1/runs/run-1/context", headers=headers)
        assert context.status_code == 200
        assert context.json()["context"]["request_text"] == "hello"
