from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient
from tests.support.production_runtime import (
    build_test_production_container as build_container,
)

from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.runtime.safe_mode import SafeModeController
from google_work_agent.adapters.system.filesystem_backup import FilesystemBackupAdapter
from google_work_agent.adapters.system.process_maintenance_gate import (
    ProcessMaintenanceGateAdapter,
)
from google_work_agent.adapters.system.system_clock import SystemClockAdapter
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import (
    CoreInitializationError,
    DeferredApiContainer,
    build_safe_mode_recovery_bindings,
)
from google_work_agent.api.container import ApiContainer


@pytest.mark.parametrize(
    "safe_code",
    ("MIGRATION_FAILED", "MCP_HANDSHAKE_FAILED", "KEYRING_UNAVAILABLE"),
)
def test_core_failure__keeps_health__and_blocks_commands(safe_code: str) -> None:
    def fail_core(**_: object) -> NoReturn:
        raise CoreInitializationError(safe_code)

    container = _shell(core_builder=fail_core)
    with TestClient(create_app(cast(ApiContainer, container))) as client:
        headers = _headers()
        _bootstrap(client, headers)

        assert client.get("/health/live", headers=headers).status_code == 200
        ready = client.get("/health/ready", headers=headers)
        assert ready.json()["status"] == "SAFE_MODE"
        assert _details(ready.json()) == {safe_code}

        runtime = client.get("/api/v1/runtime", headers=headers)
        assert runtime.status_code == 200
        assert runtime.json()["safe_mode"] is True

        command = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "schema_version": 1,
                "command_id": "command-1",
                "title": "blocked",
            },
        )
        assert command.status_code == 409
        assert command.json()["detail_code"] == "SAFE_MODE_BLOCKED"


def test_initializing_window__is_live_blocked__then_becomes_ready(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def delayed_core(
        *,
        host: str,
        port: int,
        bootstrap_secret: str,
        service_instance_id: str,
        safe_mode_controller: SafeModeController,
    ) -> ApiContainer:
        started.set()
        assert release.wait(timeout=10)
        return build_container(
            host=host,
            port=port,
            runtime_root=tmp_path / "runtime",
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            safe_mode_controller=safe_mode_controller,
            mcp_module_name="tests.fakes.google_workspace_mcp_server",
            keyring_store=SessionMemorySecretStore(),
        )

    container = _shell(core_builder=delayed_core)
    initialization = threading.Thread(target=lambda: asyncio.run(container._initialize()))
    initialization.start()
    assert started.wait(timeout=5)
    assert container.core_initialization_in_progress is True
    assert container._core is None

    release.set()
    initialization.join(timeout=15)
    assert not initialization.is_alive()
    assert container.core_initialization_in_progress is False
    assert container._core is not None
    container.close()


def test_start_run_reaches__the_durable_execution__runtime_after_core_initialization(
    tmp_path: Path,
) -> None:
    """POST /runs commits and schedules through the bound durable runtime."""

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True)
    database_path = runtime_root / "data" / "google_work_agent.db"
    database_path.parent.mkdir(parents=True)
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Existing conversation', 1, 1);
            """
        )
    finally:
        connection.close()

    container = _shell(
        core_builder=lambda **kwargs: build_container(
            runtime_root=runtime_root,
            mcp_module_name="tests.fakes.google_workspace_mcp_server",
            keyring_store=SessionMemorySecretStore(),
            **kwargs,
        )
    )
    with TestClient(create_app(cast(ApiContainer, container))) as client:
        headers = _headers()
        _bootstrap(client, headers)
        assert _wait_for_ready(client, headers) == "READY"
        assert container._core is not None
        assert isinstance(container._core.workflow_runtime, LangGraphWorkflowRuntime)

        response = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "api_contract_version": "1",
                "command_id": "start-command-1",
                "conversation_id": "conversation-1",
                "request_text": "hello",
                "entry_mode": "AGENT_SEARCH",
                "selected_resource_handles": [],
                "requested_mode": "AUTO",
            },
        )

        assert response.status_code == 202, response.json()
        assert response.json().get("detail_code") != "AttributeError"


def test_shutdown_awaits__inflight_initialization_and__closes_late_core(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()

    def delayed_core(
        *,
        host: str,
        port: int,
        bootstrap_secret: str,
        service_instance_id: str,
        safe_mode_controller: SafeModeController,
    ) -> ApiContainer:
        started.set()
        assert release.wait(timeout=10)
        return build_container(
            host=host,
            port=port,
            runtime_root=tmp_path / "runtime",
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            safe_mode_controller=safe_mode_controller,
            mcp_module_name="tests.fakes.google_workspace_mcp_server",
            keyring_store=SessionMemorySecretStore(),
        )

    container = _shell(core_builder=delayed_core)
    with TestClient(create_app(cast(ApiContainer, container))):
        assert started.wait(timeout=5)
        threading.Timer(0.05, release.set).start()

    assert container._closed is True
    assert container._core is None


def test_deferred_initialization_runs__core_reconciliation_startup__and_shutdown_once() -> None:
    lifecycle: list[str] = []

    async def startup() -> None:
        lifecycle.append("initial-drain-and-live-start")

    core = SimpleNamespace(
        readiness_aggregator=SimpleNamespace(),
        current_account_id_provider=lambda: None,
        startup_callbacks=(startup,),
        shutdown_callbacks=(lambda: lifecycle.append("runtime-stop"),),
    )
    container = _shell(core_builder=lambda **_: cast(ApiContainer, core))

    asyncio.run(container._initialize())
    container.close()
    container.close()

    assert lifecycle == [
        "initial-drain-and-live-start",
        "runtime-stop",
    ]


def test_safe_mode__restore_migrates_then__rebinds_ready_core(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    database_path = runtime_root / "data" / "google_work_agent.db"
    database_path.parent.mkdir(parents=True)
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-restored', 'restored@example.com', 'Restored', 1);"
        )
    finally:
        connection.close()
    backup_adapter = FilesystemBackupAdapter(
        database_path=database_path,
        backups_dir=runtime_root / "backups",
        clock=SystemClockAdapter(),
        maintenance_gate=ProcessMaintenanceGateAdapter(has_active_write=lambda: False),
        release_version="test",
        domain_contract_version="1",
        schema_version="0019",
    )
    backup_adapter.create_backup("seed-safe-mode-restore")
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "UPDATE schema_migrations SET checksum=? WHERE version=1;", ("0" * 64,)
        )
    finally:
        connection.close()
    attempts = 0

    def core_builder(**kwargs: object) -> ApiContainer:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise CoreInitializationError("MIGRATION_FAILED")
        return build_container(
            host=cast(str, kwargs["host"]),
            port=cast(int, kwargs["port"]),
            runtime_root=runtime_root,
            bootstrap_secret=cast(str | None, kwargs["bootstrap_secret"]),
            service_instance_id=cast(str | None, kwargs["service_instance_id"]),
            safe_mode_controller=cast(
                SafeModeController | None, kwargs["safe_mode_controller"]
            ),
            mcp_module_name="tests.fakes.google_workspace_mcp_server",
            keyring_store=SessionMemorySecretStore(),
        )

    container = DeferredApiContainer(
        host="127.0.0.1",
        port=8000,
        service_instance_id="svc-startup",
        bootstrap_secret="bootstrap-secret",
        core_builder=core_builder,
        recovery_builder=lambda retry: build_safe_mode_recovery_bindings(
            runtime_root=runtime_root,
            release_version="test",
            retry_core_after_restore=retry,
            request_process_exit=lambda: None,
        ),
    )
    container.client_address_resolver = lambda _request: "127.0.0.1"
    with TestClient(create_app(cast(ApiContainer, container))) as client:
        headers = _headers()
        _bootstrap(client, headers)
        assert client.get("/health/ready", headers=headers).json()["status"] == "READY"
        assert attempts == 2
        blocked = client.post(
            "/api/v1/restore",
            headers={**headers, "x-api-contract-version": "1"},
            json={
                "schema_version": 1,
                "command_id": "restore-command-1",
                "backup_ref": "not-used-while-ready",
            },
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail_code"] == "RESTORE_REQUIRES_SAFE_MODE"


def _shell(*, core_builder: Callable[..., ApiContainer]) -> DeferredApiContainer:
    container = DeferredApiContainer(
        host="127.0.0.1",
        port=8000,
        service_instance_id="svc-startup",
        bootstrap_secret="bootstrap-secret",
        core_builder=core_builder,
    )
    container.client_address_resolver = lambda _request: "127.0.0.1"
    return container


def _headers() -> dict[str, str]:
    return {
        "host": "127.0.0.1:8000",
        "origin": "http://127.0.0.1:8000",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
    }


def _bootstrap(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/session/bootstrap",
        headers=headers,
        json={
            "schema_version": 1,
            "bootstrap_secret": "bootstrap-secret",
            "frontend_api_contract_version": "1",
        },
    )
    assert response.status_code == 200


def _details(payload: dict[str, object]) -> set[str]:
    checks = cast(list[dict[str, object]], payload["checks"])
    return {str(check["detail"]) for check in checks if check["detail"] is not None}


def _wait_for_ready(client: TestClient, headers: dict[str, str]) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get("/health/ready", headers=headers)
        status = str(response.json()["status"])
        if status == "READY":
            return status
        time.sleep(0.05)
    raise AssertionError("core did not become ready")
