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

from fastapi.testclient import TestClient
from uvicorn import Config, Server

from google_work_agent.api import create_app
from google_work_agent.launcher.dev import DevelopmentReadinessAggregator, build_container


def test_development_container_serves_health_and_closes_mcp_child(tmp_path: Path) -> None:
    container = build_container(
        runtime_root=tmp_path / "runtime",
        bootstrap_secret="test-bootstrap",
    )
    container = replace(container, client_address_resolver=lambda _request: "127.0.0.1")

    with TestClient(create_app(container), base_url="http://127.0.0.1:8000") as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

        assert live.status_code == 200
        assert live.json()["status"] == "LIVE"
        assert ready.status_code == 200
        assert ready.json()["status"] == "READY"
        assert container.runtime_status_provider.get_summary().mcp == "READY"

    assert isinstance(container.readiness_aggregator, DevelopmentReadinessAggregator)
    assert container.readiness_aggregator.transport.runtime_metadata().process_status == "STOPPED"
    assert container.readiness_aggregator.evaluate().state.value == "NOT_READY"


def test_development_service_serves_loopback_health_over_uvicorn(tmp_path: Path) -> None:
    port = _allocate_loopback_port()
    container = build_container(
        port=port,
        runtime_root=tmp_path / "runtime",
        bootstrap_secret="test-bootstrap",
    )
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
    assert isinstance(container.readiness_aggregator, DevelopmentReadinessAggregator)
    assert container.readiness_aggregator.transport.runtime_metadata().process_status == "STOPPED"


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
