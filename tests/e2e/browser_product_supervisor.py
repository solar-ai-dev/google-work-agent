"""Test-only child-process supervisor for Browser restart E2E."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.error import URLError
from urllib.request import urlopen

_HOST = "127.0.0.1"
_CONTROL_PORT = int(os.environ.get("GWA_BROWSER_E2E_CONTROL_PORT", "18766"))
_BACKEND_PORT = int(os.environ.get("GWA_BROWSER_E2E_PORT", "18765"))
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class BackendSupervisor:
    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._generation = 0
        self._crash_enabled = True

    def start(self) -> None:
        with self._lock:
            self._start_locked()

    def restart(self, *, disable_crash: bool) -> dict[str, object]:
        with self._lock:
            self._stop_locked()
            if disable_crash:
                self._crash_enabled = False
            self._start_locked()
            process = self._required_process()
            return {"generation": self._generation, "pid": process.pid}

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def state(self) -> dict[str, object]:
        with self._lock:
            process = self._process
            return {
                "generation": self._generation,
                "pid": None if process is None else process.pid,
                "running": process is not None and process.poll() is None,
                "crash_enabled": self._crash_enabled,
            }

    def is_ready(self) -> bool:
        process = self._process
        return (
            process is not None
            and process.poll() is None
            and _backend_is_live()
        )

    def _start_locked(self) -> None:
        child_environment = os.environ.copy()
        if self._crash_enabled:
            child_environment.update(
                {
                    "GWA_BROWSER_E2E_CRASH_PROMPT_ID": "retrieval.select_evidence",
                    "GWA_BROWSER_E2E_CRASH_SCENARIO": "PROCESS_RESTART",
                }
            )
        else:
            child_environment.pop("GWA_BROWSER_E2E_CRASH_PROMPT_ID", None)
            child_environment.pop("GWA_BROWSER_E2E_CRASH_SCENARIO", None)
        creationflags = (
            cast(int, getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            if sys.platform == "win32"
            else 0
        )
        self._process = subprocess.Popen(
            [sys.executable, "-m", "tests.e2e.browser_product_server"],
            cwd=_REPOSITORY_ROOT,
            env=child_environment,
            creationflags=creationflags,
            start_new_session=sys.platform != "win32",
        )
        self._generation += 1
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            process = self._required_process()
            if process.poll() is not None:
                raise RuntimeError(f"Browser Product backend exited with {process.returncode}")
            if _backend_is_live():
                return
            time.sleep(0.05)
        raise TimeoutError("Browser Product backend did not become ready")

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        if process is None or process.poll() is not None:
            return
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)

    def _required_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise RuntimeError("Browser Product backend is not running")
        return self._process


class SupervisorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health/live":
            self._json_response(
                200 if _SUPERVISOR.is_ready() else 503,
                _SUPERVISOR.state(),
            )
            return
        if self.path == "/state":
            self._json_response(200, _SUPERVISOR.state())
            return
        self._json_response(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/restart":
            payload = self._request_json()
            result = _SUPERVISOR.restart(
                disable_crash=payload.get("disable_crash") is True,
            )
            self._json_response(200, result)
            return
        if self.path == "/shutdown":
            self._json_response(202, {"status": "shutting_down"})
            threading.Thread(target=_HTTP_SERVER.shutdown, daemon=True).start()
            return
        self._json_response(404, {"error": "not_found"})

    def log_message(self, _format: str, *args: Any) -> None:
        del args

    def _request_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        payload = json.loads(self.rfile.read(content_length))
        if not isinstance(payload, dict):
            raise ValueError("supervisor request body must be an object")
        return cast(dict[str, object], payload)

    def _json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _backend_is_live() -> bool:
    try:
        with urlopen(f"http://{_HOST}:{_BACKEND_PORT}/health/live", timeout=0.5) as response:
            return cast(int, response.status) == 200
    except (OSError, URLError):
        return False


_SUPERVISOR = BackendSupervisor()
_HTTP_SERVER = ThreadingHTTPServer((_HOST, _CONTROL_PORT), SupervisorHandler)


def main() -> None:
    _SUPERVISOR.start()
    try:
        _HTTP_SERVER.serve_forever()
    finally:
        _SUPERVISOR.stop()
        _HTTP_SERVER.server_close()


if __name__ == "__main__":
    main()
