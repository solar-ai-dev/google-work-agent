from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, cast

import pytest
from fastapi.testclient import TestClient

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.runtime import SafeModeController
from google_work_agent.api.app import create_app
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.write_actions import ResolveMismatchRecoveryService
from google_work_agent.launcher.dev import (
    CoreInitializationError,
    _DeferredApiContainer,
    build_container,
)


@pytest.mark.parametrize(
    "safe_code",
    ("MIGRATION_FAILED", "MCP_HANDSHAKE_FAILED", "KEYRING_UNAVAILABLE"),
)
def test_core_failure_keeps_health_and_blocks_commands(safe_code: str) -> None:
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
        assert runtime.json()["summary"]["safe_mode"] is True

        command = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "api_contract_version": "1",
                "command_id": "command-1",
                "conversation_id": "conversation-1",
                "account_id": "account-1",
                "title": "blocked",
            },
        )
        assert command.status_code == 409
        assert command.json()["detail_code"] == "SAFE_MODE_BLOCKED"


def test_initializing_window_is_live_blocked_then_becomes_ready(tmp_path: Path) -> None:
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
        )

    container = _shell(core_builder=delayed_core)
    with TestClient(create_app(cast(ApiContainer, container))) as client:
        assert started.wait(timeout=5)
        headers = _headers()
        _bootstrap(client, headers)

        assert client.get("/health/live", headers=headers).json()["status"] == "LIVE"
        assert client.get("/health/ready", headers=headers).json()["status"] == "NOT_READY"
        blocked = client.post(
            "/api/v1/conversations",
            headers=headers,
            json={
                "api_contract_version": "1",
                "command_id": "command-1",
                "conversation_id": "conversation-1",
                "account_id": "account-1",
                "title": "blocked",
            },
        )
        assert blocked.json()["detail_code"] == "SAFE_MODE_BLOCKED"

        release.set()
        assert _wait_for_ready(client, headers) == "READY"
        assert container._core is not None
        assert isinstance(
            container._core.resolve_recovery_service,
            ResolveMismatchRecoveryService,
        )


def test_start_run_reaches_the_real_coordinator_once_core_initialization_completes(
    tmp_path: Path,
) -> None:
    """Regression test: POST /api/v1/runs used to return 503 SERVICE_BUSY with
    detail_code=AttributeError even after core initialization finished,
    because `local_run_coordinator` never delegated enqueue_start to the
    real, now-bound LocalRunCoordinator (see _DeferredCoordinator)."""

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True)
    database_path = runtime_root / "google-work-agent.sqlite3"
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
        core_builder=lambda **kwargs: build_container(runtime_root=runtime_root, **kwargs)
    )
    with TestClient(create_app(cast(ApiContainer, container))) as client:
        headers = _headers()
        _bootstrap(client, headers)
        assert _wait_for_ready(client, headers) == "READY"

        response = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "api_contract_version": "1",
                "command_id": "start-command-1",
                "conversation_id": "conversation-1",
                "user_message_id": "message-1",
                "run_id": "run-1",
                "workflow_key": "workflow-run-1",
                "request_text": "hello",
                "entry_mode": "AGENT_SEARCH",
                "selected_resource_ids": [],
                "selected_resources": [],
                "requested_mode": "AUTO",
            },
        )

        assert response.status_code == 202, response.json()
        assert response.json().get("detail_code") != "AttributeError"


def test_shutdown_awaits_inflight_initialization_and_closes_late_core(tmp_path: Path) -> None:
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
        )

    container = _shell(core_builder=delayed_core)
    with TestClient(create_app(cast(ApiContainer, container))):
        assert started.wait(timeout=5)
        threading.Timer(0.05, release.set).start()

    assert container._closed is True
    assert container._core is None


def _shell(*, core_builder: Callable[..., ApiContainer]) -> _DeferredApiContainer:
    container = _DeferredApiContainer(
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
            "bootstrap_secret": "bootstrap-secret",
            "service_instance_id": "svc-startup",
            "api_contract_version": "1",
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
