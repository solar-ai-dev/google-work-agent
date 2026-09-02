from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import launcher.entrypoint as entrypoint


class _Lease:
    def __init__(self, *, acquired: bool) -> None:
        self.acquired = acquired
        self.control_endpoint = r"\\.\pipe\GoogleWorkAgent-user"

    def bind_service_instance(self, _service_instance_id: str) -> _Lease:
        return self


class _Reservation:
    port = 43123

    def __init__(self) -> None:
        self.released = False

    def release(self) -> None:
        self.released = True


class _Identity:
    service_instance_id = "instance-1"
    port = 43123

    def bind_service_pid(self, _pid: int) -> _Identity:
        return self


class _Service:
    pid = 100

    def __init__(self) -> None:
        self.return_code: int | None = None

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.return_code = 0
        return 0


def test_main_executes__canonical_new__instance_order(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    lease = _Lease(acquired=True)
    reservation = _Reservation()
    identity = _Identity()
    service = _Service()
    layout = SimpleNamespace(
        runtime_dir=tmp_path / "runtime",
        shutdown_marker_path=tmp_path / "runtime" / "shutdown.marker",
    )
    build_config = SimpleNamespace(app_version="1.2.3", api_contract_version="1")

    def record(name: str, result: object) -> Callable[..., object]:
        def callback(*_args: object, **_kwargs: object) -> object:
            calls.append(name)
            return result

        return callback

    monkeypatch.setattr(entrypoint, "verify_installation", record("verify", object()))
    monkeypatch.setattr(entrypoint, "load_signed_build_config", record("config", build_config))
    monkeypatch.setattr(entrypoint, "prepare_data_directory", record("data", layout))
    monkeypatch.setattr(entrypoint, "acquire_single_instance", record("lock", lease))
    monkeypatch.setattr(entrypoint, "allocate_dynamic_port", record("port", reservation))
    monkeypatch.setattr(entrypoint, "create_bootstrap_secret", record("secret", "secret"))
    monkeypatch.setattr(entrypoint, "create_service_instance_id", record("identity", identity))
    monkeypatch.setattr(entrypoint, "start_service", record("start", service))
    monkeypatch.setattr(entrypoint, "wait_for_service_ready", record("readiness", object()))
    monkeypatch.setattr(entrypoint, "serve_instance_control", record("control", object()))
    monkeypatch.setattr(entrypoint, "open_product_ui", record("browser", "url"))
    monkeypatch.setattr(entrypoint, "shutdown_service", record("shutdown", object()))
    monkeypatch.setattr(entrypoint, "DefaultBrowserLauncherAdapter", lambda: object())

    result = entrypoint.main(
        [
            "--install-root",
            str(tmp_path.resolve()),
            "--startup-timeout",
            "1",
            "--shutdown-timeout",
            "1",
        ]
    )

    assert result == 0
    assert calls == [
        "verify",
        "config",
        "data",
        "lock",
        "port",
        "secret",
        "identity",
        "start",
        "readiness",
        "control",
        "browser",
        "shutdown",
    ]
    assert reservation.released is True


def test_main_existing__instance_requests_ui__without_starting_service(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    layout = SimpleNamespace(runtime_dir=tmp_path, shutdown_marker_path=tmp_path / "marker")
    monkeypatch.setattr(entrypoint, "verify_installation", lambda _root: object())
    monkeypatch.setattr(entrypoint, "load_signed_build_config", lambda _install: object())
    monkeypatch.setattr(entrypoint, "prepare_data_directory", lambda: layout)
    monkeypatch.setattr(
        entrypoint,
        "acquire_single_instance",
        lambda _runtime: _Lease(acquired=False),
    )
    monkeypatch.setattr(
        entrypoint,
        "request_existing_instance_ui",
        lambda _endpoint: _record_request(calls),
    )
    monkeypatch.setattr(
        entrypoint,
        "start_service",
        lambda **_kwargs: calls.append("unexpected-start"),
    )
    monkeypatch.setattr(
        entrypoint,
        "shutdown_service",
        lambda **_kwargs: calls.append("unexpected-shutdown"),
    )

    result = entrypoint.main(["--install-root", str(tmp_path.resolve())])

    assert result == 0
    assert calls == ["request-ui"]


def _record_request(calls: list[str]) -> bool:
    calls.append("request-ui")
    return True
