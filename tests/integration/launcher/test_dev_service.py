from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import cast
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient
from tests.support.production_runtime import (
    build_test_production_container as build_container,
)
from uvicorn import Config, Server

from google_work_agent.adapters.langgraph.main.workflow import LangGraphWorkflowRuntime
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.readiness.local_service_readiness import (
    LocalServiceReadinessAggregator,
)
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    ATTACHMENT_STAGING_DIR_ENV,
)
from google_work_agent.api.app import create_app
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentCommand,
    CreateStagedAttachmentHandler,
)


def test_development_container_serves_health_and_closes_mcp_child(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    container = build_container(
        runtime_root=runtime_root,
        bootstrap_secret="test-bootstrap",
        mcp_module_name="tests.fakes.google_workspace_mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    container = replace(container, client_address_resolver=lambda _request: "127.0.0.1")

    assert isinstance(container.workflow_runtime, LangGraphWorkflowRuntime)
    assert container.get_attachment_handler is not None
    assert isinstance(container.create_staged_attachment_handler, CreateStagedAttachmentHandler)
    descriptor = container.create_staged_attachment_handler(
        CreateStagedAttachmentCommand(
            command_id="stage-attachment-test",
            file_bytes=b"attachment-content",
            filename="report.txt",
            mime_type="text/plain",
        )
    ).attachment
    staging_dir = runtime_root / "cache" / "attachments"
    assert (staging_dir / f"{descriptor.staged_attachment_id}.bin").is_file()
    readiness = cast(LocalServiceReadinessAggregator, container.readiness_aggregator)
    base_transport = readiness.transport.client
    assert base_transport._config.extra_environment == {
        ATTACHMENT_STAGING_DIR_ENV: str(staging_dir.resolve()),
        "GOOGLE_OAUTH_ENV": "DEVELOPMENT",
        "GOOGLE_OAUTH_CLIENT_ID": "test-client-id",
    }

    with TestClient(create_app(container), base_url="http://127.0.0.1:8000") as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

        assert live.status_code == 200
        assert live.json()["status"] == "LIVE"
        assert ready.status_code == 200
        assert ready.json()["status"] == "READY"

    assert isinstance(container.readiness_aggregator, LocalServiceReadinessAggregator)
    assert base_transport.runtime_metadata().process_status == "STOPPED"
    assert container.readiness_aggregator.evaluate().state.value == "NOT_READY"


def test_development_service_serves_loopback_health_over_uvicorn(tmp_path: Path) -> None:
    port = _allocate_loopback_port()
    container = build_container(
        port=port,
        runtime_root=tmp_path / "runtime",
        bootstrap_secret="test-bootstrap",
        mcp_module_name="tests.fakes.google_workspace_mcp_server",
        keyring_store=SessionMemorySecretStore(),
    )
    readiness = cast(LocalServiceReadinessAggregator, container.readiness_aggregator)
    base_transport = readiness.transport.client
    server = Server(Config(create_app(container), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        live = _get_json(f"http://127.0.0.1:{port}/health/live")
        ready = _get_json(f"http://127.0.0.1:{port}/health/ready")

        assert live["status"] == "LIVE"
        assert ready["status"] == "READY"
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert isinstance(container.readiness_aggregator, LocalServiceReadinessAggregator)
    assert base_transport.runtime_metadata().process_status == "STOPPED"


@pytest.mark.parametrize("graph_profile", tuple(GraphProfile))
def test_development_container_selects_each_canonical_graph_profile(
    tmp_path: Path,
    graph_profile: GraphProfile,
) -> None:
    container = build_container(
        runtime_root=tmp_path / graph_profile.value,
        bootstrap_secret="test-bootstrap",
        mcp_module_name="tests.fakes.google_workspace_mcp_server",
        keyring_store=SessionMemorySecretStore(),
        graph_profile=graph_profile,
    )
    try:
        runtime = cast(LangGraphWorkflowRuntime, container.workflow_runtime)
        assert container.graph_profile == graph_profile.value
        assert runtime.graph_profile() is graph_profile
        assert runtime._graph.get_graph().nodes
    finally:
        for callback in container.shutdown_callbacks:
            callback()


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


def _get_json(url: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise AssertionError("health response must be an object")
                return cast(dict[str, object], payload)
        except URLError:
            time.sleep(0.05)
    raise AssertionError(f"service did not become available: {url}")
