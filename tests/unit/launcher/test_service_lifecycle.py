from __future__ import annotations

import io
import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.open_product_ui import open_product_ui
from launcher.prepare_data_directory import prepare_data_directory
from launcher.readiness import ServiceReadinessError, wait_for_service_ready
from launcher.release_build_config import SignedBuildConfigV1
from launcher.request_existing_instance_ui import request_existing_instance_ui
from launcher.serve_instance_control import serve_instance_control
from launcher.shutdown_service import shutdown_service
from launcher.start_service import StartedService, start_service
from launcher.verify_installation import VerifiedInstallation


class _CaptureStdin(io.BytesIO):
    def close(self) -> None:
        self.closed_by_launcher = True


class _Process:
    def __init__(self, *, wait_result: int = 0, wait_timeout: bool = False) -> None:
        self.pid = 4321
        self.stdin = _CaptureStdin()
        self._return_code: int | None = None
        self.wait_result = wait_result
        self.wait_timeout = wait_timeout
        self.signals: list[object] = []
        self.killed = False

    def poll(self) -> int | None:
        return self._return_code

    def wait(self, timeout: float | None = None) -> int:
        if self.wait_timeout and not self.killed:
            raise subprocess.TimeoutExpired("service", timeout or 0)
        self._return_code = self.wait_result
        return self.wait_result

    def send_signal(self, signal: object) -> None:
        self.signals.append(signal)

    def terminate(self) -> None:
        self.signals.append("terminate")

    def kill(self) -> None:
        self.killed = True
        self._return_code = self.wait_result


def _build_config() -> SignedBuildConfigV1:
    return SignedBuildConfigV1(
        schema_version=1,
        app_version="1.2.3",
        build_channel="STABLE",
        deployment_profile="LOCAL_CAPABLE",
        oauth_env="PRODUCTION",
        oauth_client_id="desktop-client-id",
        api_contract_version="1",
        mcp_schema_version="2026-08-07.p0",
        policy_version="2026-08-06.p0",
        database_migration_version="0001",
    )


def test_service_start_uses__verified_executable_and__stdin_only_for_secret(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "install" / "service" / "GoogleWorkAgentService.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"service")
    uninstaller = tmp_path / "install" / "unins000.exe"
    uninstaller.write_bytes(b"uninstaller")
    installation = VerifiedInstallation(
        install_root=(tmp_path / "install").resolve(),
        manifest_path=tmp_path / "install" / "release-manifest.json",
        signature_path=tmp_path / "install" / "release-manifest.sig",
        manifest=MappingProxyType(
            {
                "files": [
                    {
                        "file_path": "service/GoogleWorkAgentService.exe",
                        "file_size": executable.stat().st_size,
                        "sha256": "0" * 64,
                    }
                ]
            }
        ),
        verified_files=(executable.resolve(),),
        code_signature_verified_files=(executable.resolve(), uninstaller.resolve()),
    )
    layout = prepare_data_directory(tmp_path / "data", acl_initializer=lambda _path: None)
    reservation = allocate_dynamic_port()
    process = _Process()
    captured: dict[str, Any] = {}

    def process_factory(command: list[str], **kwargs: Any) -> _Process:
        captured["command"] = command
        captured.update(kwargs)
        return process

    started = start_service(
        installation=installation,
        build_config=_build_config(),
        data_directory=layout,
        port_reservation=reservation,
        service_instance_id="service-instance",
        bootstrap_secret="one-time-secret",
        process_factory=process_factory,
    )

    payload = json.loads(process.stdin.getvalue())
    assert started.pid == 4321
    assert captured["command"][0] == str(executable.resolve())
    assert captured["command"][1:] == [
        "--host",
        "127.0.0.1",
        "--port",
        str(reservation.port),
        "--data-dir",
        str(layout.root),
    ]
    assert "one-time-secret" not in " ".join(captured["command"])
    assert "one-time-secret" not in json.dumps(captured["env"])
    assert payload["bootstrap_secret"] == "one-time-secret"
    assert payload["signed_build_config"]["oauth_client_id"] == "desktop-client-id"
    assert payload["verified_release_files"] == installation.manifest["files"]
    assert payload["code_signature_verified_paths"] == ["service/GoogleWorkAgentService.exe"]
    assert "client_secret" not in payload["signed_build_config"]
    assert process.stdin.closed_by_launcher is True


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.content = json.dumps(payload).encode()

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self.content


def test_readiness_requires__matching_live_and__all_ready_checks() -> None:
    process = _Process()
    service = StartedService(process=process, executable_path=Path("service.exe"))
    live_payload: dict[str, object] = {
        "status": "LIVE",
        "service_instance_id": "instance-1",
        "release_version": "1.2.3",
        "api_contract_version": "1",
    }
    ready_payload: dict[str, object] = {
        "status": "READY",
        "checks": [{"name": "core", "state": "READY"}],
        "release_version": "1.2.3",
        "api_contract_version": "1",
    }
    responses: Iterator[dict[str, object]] = iter((live_payload, ready_payload))

    result = wait_for_service_ready(
        service,
        port=54321,
        service_instance_id="instance-1",
        expected_release_version="1.2.3",
        expected_api_contract_version="1",
        opener=lambda *_args, **_kwargs: _Response(next(responses)),
        sleep=lambda _seconds: None,
    )

    assert result.state == "READY"


def test_readiness_stops__immediately_when__child_exits() -> None:
    process = _Process()
    process._return_code = 3
    service = StartedService(process=process, executable_path=Path("service.exe"))

    with pytest.raises(ServiceReadinessError, match="SERVICE_EARLY_EXIT"):
        wait_for_service_ready(
            service,
            port=54321,
            service_instance_id="instance-1",
            expected_release_version="1.2.3",
            expected_api_contract_version="1",
        )


class _Browser:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def open_url(self, url: str) -> None:
        self.urls.append(url)


def test_browser_bootstrap_is__fragment_only_and__existing_open_is_bare() -> None:
    browser = _Browser()
    bootstrap_url = open_product_ui(
        browser,
        port=43210,
        bootstrap_secret="one-time-secret",
        service_instance_id="instance-1",
    )
    existing_url = open_product_ui(browser, port=43210)

    parsed = urlsplit(bootstrap_url)
    assert parsed.query == ""
    assert parse_qs(parsed.fragment) == {
        "bootstrap_secret": ["one-time-secret"],
        "service_instance_id": ["instance-1"],
    }
    assert existing_url == "http://127.0.0.1:43210/"


class _ClientConnection:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.closed = False

    def send_bytes(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv_bytes(self, _maximum: int) -> bytes:
        return self.response

    def close(self) -> None:
        self.closed = True


class _ServerConnection:
    def __init__(self, request: bytes) -> None:
        self.request = request
        self.sent: list[bytes] = []

    def recv_bytes(self, _maximum: int) -> bytes:
        return self.request

    def send_bytes(self, payload: bytes) -> None:
        self.sent.append(payload)

    def close(self) -> None:
        return None


class _Listener:
    def __init__(self, connection: _ServerConnection) -> None:
        self.connection = connection
        self.accepted = False

    def accept(self) -> _ServerConnection:
        if self.accepted:
            raise OSError("closed")
        self.accepted = True
        return self.connection

    def close(self) -> None:
        return None


def test_instance_control__server_accepts__only_open_ui() -> None:
    connection = _ServerConnection(b'{"schema_version":1,"command":"DELETE_DATA"}')
    opened: list[bool] = []
    server = serve_instance_control(
        r"\\.\pipe\GoogleWorkAgent-current-user",
        on_open_ui=lambda: opened.append(True),
        listener_factory=lambda _endpoint, _authkey: _Listener(connection),
    )
    deadline = time.monotonic() + 1
    while server.is_alive and time.monotonic() < deadline:
        time.sleep(0.01)
    server.close()

    assert opened == []
    assert json.loads(connection.sent[0]) == {"schema_version": 1, "status": "REJECTED"}


def test_existing_instance__control_has__one_closed_command() -> None:
    connection = _ClientConnection(b'{"schema_version":1,"status":"ACCEPTED"}')
    result = request_existing_instance_ui(
        r"\\.\pipe\GoogleWorkAgent-current-user",
        wait_for_endpoint=lambda _endpoint, _timeout: True,
        client_factory=lambda _endpoint, _authkey: connection,
    )

    assert result is True
    assert connection.sent == [b'{"command":"OPEN_UI","schema_version":1}']
    assert connection.closed is True


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Clearable:
    def __init__(self) -> None:
        self.service_instance_id = "instance-1"
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _Releasable:
    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


def test_shutdown_forces_only__after_timeout_and__always_settles_artifacts(
    tmp_path: Path,
) -> None:
    process = _Process(wait_result=0, wait_timeout=True)
    service = StartedService(process=process, executable_path=Path("service.exe"))
    control = _Closable()
    identity = _Clearable()
    lease = _Releasable()
    marker = tmp_path / "shutdown.marker"

    result = shutdown_service(
        service=service,
        control_server=control,  # type: ignore[arg-type]
        identity=identity,  # type: ignore[arg-type]
        lease=lease,  # type: ignore[arg-type]
        marker_path=marker,
        timeout_seconds=0.1,
        now_ms=99,
    )

    assert result.forced is True
    assert process.killed is True
    assert control.closed is True
    assert identity.cleared is True
    assert lease.released is True
    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "service_instance_id": "instance-1",
        "status": "UNCLEAN",
        "completed_at_ms": 99,
        "exit_code": 0,
        "forced": True,
        "safe_error_code": None,
    }
