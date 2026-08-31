from __future__ import annotations

import threading
import uuid

from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.request_existing_instance_ui import request_existing_instance_ui
from launcher.serve_instance_control import serve_instance_control


def test_dynamic_loopback_port_allocator_returns_positive_port() -> None:
    reservation = allocate_dynamic_port()
    port = reservation.port
    reservation.release()

    assert port > 0


def test_current_user_named_pipe_control_round_trip() -> None:
    endpoint = rf"\\.\pipe\GoogleWorkAgent-test-{uuid.uuid4().hex}"
    opened = threading.Event()
    server = serve_instance_control(endpoint, on_open_ui=opened.set)
    try:
        assert request_existing_instance_ui(endpoint, timeout_seconds=2) is True
        assert opened.wait(timeout=2)
    finally:
        server.close()
