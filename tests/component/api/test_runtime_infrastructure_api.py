from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient
from tests.support.fakes import DeterministicUUID, FakeClockPort

from google_work_agent.adapters.readiness.composite import (
    StaticLauncherProbeVerifier,
    StaticReadinessAggregator,
    StaticRuntimeStatusProvider,
)
from google_work_agent.adapters.runtime import (
    BuildProfile,
    FileSettingsStore,
    FrontendSite,
    RestorePlanner,
    SafeModeController,
)
from google_work_agent.adapters.runtime.build_manifest import hash_file
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.json_settings import JsonSettingsAdapter
from google_work_agent.adapters.system.process_shutdown import ProcessShutdownAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.settings import (
    CreateBackupService,
    CreateRestorePlanService,
    GetSettingsService,
    ListBackupsService,
    PatchSettingsService,
    RequestShutdownService,
)
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    BufferStatus,
    EndpointPolicy,
    LauncherProbeDecision,
    MaintenanceWindow,
    PendingProjectionEvent,
    ProjectionEvent,
    ReadinessReport,
    ReadinessState,
    RunEventSubscription,
    RuntimeSummary,
    SseEventBufferPort,
    WorkflowCancelRequest,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
    WorkflowRuntime,
    WorkflowStartRequest,
)


class _CoordinatorStub:
    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def stop_accepting_commands(self) -> None:
        return None

    def stop_accepting(self) -> None:
        return None

    def shutdown(self, timeout_seconds: float) -> None:
        return None


class _AllowGuard:
    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        del request_context, endpoint_policy
        return AccessDecision(allowed=True)


class _PublisherStub:
    def replay(self, **kwargs):  # type: ignore[no-untyped-def]
        return ()

    def subscribe(self, run_id: str) -> RunEventSubscription:
        del run_id
        return _Subscription()

    def close_subscription(self, subscription: object) -> None:
        del subscription

    def publish(self, event: PendingProjectionEvent) -> ProjectionEvent:
        del event
        return ProjectionEvent(
            event_id="evt-1",
            run_id="run-1",
            occurred_at_ms=0,
            event_type="status",
            payload={},
            projection_version=1,
            schema_version=1,
        )

    def get_buffer_status(self, run_id: str) -> BufferStatus:
        return BufferStatus(
            run_id=run_id,
            service_instance_id="svc-runtime",
            newest_event_id=None,
            event_count=0,
            capacity=32,
        )


class _WorkflowRuntimeStub:
    def start(self, request: WorkflowStartRequest) -> WorkflowInvocationResult:
        del request
        return _workflow_result()

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        del request
        return _workflow_result()

    def request_cancel(self, request: WorkflowCancelRequest) -> WorkflowInvocationResult:
        del request
        return _workflow_result()

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult:
        del request
        return _workflow_result()

    def close(self) -> None:
        return None

    def flush_or_checkpoint(self) -> None:
        return None


class _QueryStub:
    def get_runtime_summary(self) -> RuntimeSummary:
        return RuntimeSummary(
            google="CONNECTED",
            mcp="READY",
            api_llm="NOT_CONFIGURED",
            ollama="NOT_AVAILABLE",
            deployment_profile="API_ONLY",
            recovery_required_run_ids=(),
            open_run_ids=(),
        )

    def get_run_snapshot(self, run_id: str):  # type: ignore[no-untyped-def]
        del run_id
        return None

    def get_run_execution_context(self, run_id: str):  # type: ignore[no-untyped-def]
        del run_id
        return None

    def list_conversations(self, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")

    def get_conversation(self, conversation_id: str):  # type: ignore[no-untyped-def]
        del conversation_id
        return None

    def get_latest_run_for_conversation(self, conversation_id: str):  # type: ignore[no-untyped-def]
        del conversation_id
        return None


class _MaintenanceGate:
    def snapshot(self) -> MaintenanceWindow:
        return MaintenanceWindow(
            has_active_write=False,
            migration_running=False,
            restore_running=False,
        )


class _ShutdownPort:
    def stop_accepting_commands(self) -> None:
        return None

    def stop_accepting(self) -> None:
        return None

    def shutdown(self, timeout_seconds: float) -> None:
        del timeout_seconds

    def flush_or_checkpoint(self) -> None:
        return None

    def flush(self) -> None:
        return None

    def checkpoint_wal(self) -> None:
        return None

    def close(self) -> None:
        return None

    def invalidate_all(self) -> None:
        return None


def _workflow_result() -> WorkflowInvocationResult:
    return WorkflowInvocationResult(
        run_id="run-1",
        workflow_key="workflow-1",
        outcome=WorkflowOutcome.ACCEPTED,
        payload={},
    )


class _Subscription:
    def poll(self, timeout_seconds: float):  # type: ignore[no-untyped-def]
        del timeout_seconds
        return None


@dataclass
class _StartRunStub:
    called: int = 0

    def __call__(self, command):  # type: ignore[no-untyped-def]
        self.called += 1
        raise AssertionError("safe mode should block run start before the service executes")


def test_static_settings_backup_and_safe_mode_flow(tmp_path: Path) -> None:
    frontend_root = tmp_path / "frontend"
    assets_dir = frontend_root / "assets"
    assets_dir.mkdir(parents=True)
    index = frontend_root / "index.html"
    script = assets_dir / "app.js"
    index.write_text("<!doctype html><html><body>ui</body></html>", encoding="utf-8")
    script.write_text("console.log('ui');", encoding="utf-8")
    frontend_site = FrontendSite(
        root=frontend_root,
        release_version="0.1.0",
        api_contract_version="1",
        manifest_version="1",
        asset_hashes={"assets/app.js": hash_file(script)},
    )

    database_path = tmp_path / "domain.sqlite3"
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE example (id TEXT PRIMARY KEY, value TEXT);")
        connection.execute("INSERT INTO example (id, value) VALUES ('row-1', 'ok');")
        connection.commit()
    finally:
        connection.close()

    clock = FakeClockPort(100)
    settings_store = FileSettingsStore(tmp_path / "settings" / "app-settings.json")
    settings_service = JsonSettingsAdapter(
        store=settings_store,
        deployment_profile=BuildProfile.API_ONLY,
        approved_model_ids=frozenset(),
        has_active_runs=lambda: False,
    )
    backup_service = FilesystemBackupAdapter(
        database_path=database_path,
        backups_dir=tmp_path / "backups",
        clock=clock,
        maintenance_gate=_MaintenanceGate(),
        release_version="0.1.0",
        domain_contract_version="1",
        schema_version="1",
        id_generator=DeterministicUUID(prefix="backup"),
    )
    restore_planner = RestorePlanner(
        database_path=database_path,
        backups_dir=tmp_path / "backups",
        supported_schema_version="1",
        create_pre_restore_backup=lambda: backup_service.create_backup(),
    )
    safe_mode = SafeModeController()
    start_run_stub = _StartRunStub()
    shutdown_port = _ShutdownPort()
    shutdown = ProcessShutdownAdapter(
        command_gate=shutdown_port,
        coordinator=shutdown_port,
        workflow_runtime=shutdown_port,
        observability=shutdown_port,
        persistence=shutdown_port,
        mcp_transport=shutdown_port,
        sessions=shutdown_port,
        clock=clock,
    )
    container = ApiContainer(
        unit_of_work_factory=lambda: None,
        query_service=_QueryStub(),
        create_conversation_handler=lambda command: command,
        start_run_service=start_run_stub,
        approve_action_service=lambda command: command,
        modify_action_service=lambda command: command,
        reject_action_service=lambda command: command,
        prepare_retry_service=lambda command: command,
        cancel_run_service=lambda command: command,
        resume_run_service=lambda command: command,
        workflow_runtime=cast(WorkflowRuntime, _WorkflowRuntimeStub()),
        event_publisher=cast(SseEventBufferPort, _PublisherStub()),
        readiness_aggregator=StaticReadinessAggregator(
            ReadinessReport(state=ReadinessState.READY, checks=())
        ),
        runtime_status_provider=StaticRuntimeStatusProvider(
            RuntimeSummary(
                google="CONNECTED",
                mcp="READY",
                api_llm="NOT_CONFIGURED",
                ollama="NOT_AVAILABLE",
                deployment_profile="API_ONLY",
                recovery_required_run_ids=(),
                open_run_ids=(),
            )
        ),
        api_access_guard=_AllowGuard(),
        clock=clock,
        id_generator=DeterministicUUID(prefix="req"),
        release_version="0.1.0",
        environment="test",
        service_instance_id="svc-runtime",
        launcher_probe_verifier=StaticLauncherProbeVerifier(LauncherProbeDecision(allowed=True)),
        frontend_site=frontend_site,
        safe_mode_controller=safe_mode,
        get_settings_service=GetSettingsService(settings_service),
        patch_settings_service=PatchSettingsService(settings_service),
        list_backups_service=ListBackupsService(backup_service),
        create_backup_service=CreateBackupService(backup_service),
        create_restore_plan_service=CreateRestorePlanService(restore_planner),
        request_shutdown_service=RequestShutdownService(shutdown),
    )

    with TestClient(create_app(container)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/dashboard").status_code == 200
        assert client.get("/assets/app.js").text == "console.log('ui');"
        assert client.get("/api/v1/unknown").status_code == 404
        assert client.get("/health/unknown").status_code == 404

        ready = client.get("/health/ready").json()
        assert ready["status"] == "READY"

        settings_before = client.get("/api/v1/settings").json()["settings"]
        assert settings_before["deployment_profile"] == "API_ONLY"

        settings_after = client.patch(
            "/api/v1/settings",
            json={
                "command_id": "cmd-1",
                "timezone": "Asia/Seoul",
                "approval_ttl_minutes": 35,
            },
        ).json()["settings"]
        assert settings_after["approval_ttl_minutes"] == 35

        created_backup = client.post("/api/v1/backups").json()["backup"]
        assert Path(created_backup["database_path"]).exists()
        backups = client.get("/api/v1/backups").json()["items"]
        assert backups

        restore = client.post("/api/v1/restore", json={"backup_id": backups[0]["backup_id"]})
        assert restore.status_code == 200
        assert restore.json()["plan"]["current_db_backup_required"] is True

        safe_mode.enable("DB_INTEGRITY_FAILED")
        runtime = client.get("/api/v1/runtime").json()["summary"]
        assert runtime["safe_mode"] is True
        blocked = client.post(
            "/api/v1/runs",
            json={
                "command_id": "cmd-2",
                "conversation_id": "conversation-1",
                "request_text": "hello",
                "entry_mode": "AGENT_SEARCH",
                "selected_resource_handles": [],
                "requested_mode": "API_LLM",
                "api_contract_version": "1",
            },
        )
        assert blocked.status_code == 409
        assert start_run_stub.called == 0

        shutdown_response = client.post("/api/v1/control/shutdown").json()["report"]
        assert shutdown_response["status"] == "COMPLETED"
