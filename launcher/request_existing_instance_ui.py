"""Request UI opening from the trustworthy existing Launcher instance."""

from __future__ import annotations

import ctypes
import json
import os
import time
from collections.abc import Callable
from multiprocessing.connection import Client
from typing import Any

from launcher.serve_instance_control import _control_authkey, _validate_endpoint


def request_existing_instance_ui(
    control_endpoint: str,
    *,
    timeout_seconds: float = 2.0,
    client_factory: Callable[[str, bytes], Any] | None = None,
    wait_for_endpoint: Callable[[str, float], bool] | None = None,
) -> bool:
    """Send the sole allowed control command with bounded connection waiting."""

    _validate_endpoint(control_endpoint)
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    wait = wait_for_endpoint or _wait_for_named_pipe
    if not wait(control_endpoint, timeout_seconds):
        return False
    factory = client_factory or _create_client
    try:
        connection = factory(control_endpoint, _control_authkey(control_endpoint))
        connection.send_bytes(b'{"command":"OPEN_UI","schema_version":1}')
        response: object = json.loads(connection.recv_bytes(256).decode("utf-8"))
    except (OSError, EOFError, UnicodeError, json.JSONDecodeError):
        return False
    finally:
        if "connection" in locals():
            connection.close()
    return bool(response == {"schema_version": 1, "status": "ACCEPTED"})


def _create_client(endpoint: str, authkey: bytes) -> Any:
    return Client(address=endpoint, family="AF_PIPE", authkey=authkey)


def _wait_for_named_pipe(endpoint: str, timeout_seconds: float) -> bool:
    if os.name != "nt":
        return False
    deadline = time.monotonic() + timeout_seconds
    while (remaining := deadline - time.monotonic()) > 0:
        timeout_ms = max(1, min(int(remaining * 1000), 100))
        if ctypes.windll.kernel32.WaitNamedPipeW(endpoint, timeout_ms):
            return True
        if ctypes.windll.kernel32.GetLastError() not in {2, 121, 231}:
            return False
        time.sleep(min(0.01, remaining))
    return False
