from __future__ import annotations

import threading
import uuid

import pytest
from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.request_existing_instance_ui import request_existing_instance_ui
from launcher.serve_instance_control import serve_instance_control

from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
    keyring_service_name,
)


def test_dynamic_loopback__port_allocator__returns_positive_port() -> None:
    reservation = allocate_dynamic_port()
    port = reservation.port
    reservation.release()

    assert port > 0


def test_current_user__named_pipe__control_round_trip() -> None:
    endpoint = rf"\\.\pipe\GoogleWorkAgent-test-{uuid.uuid4().hex}"
    opened = threading.Event()
    server = serve_instance_control(endpoint, on_open_ui=opened.set)
    try:
        assert request_existing_instance_ui(endpoint, timeout_seconds=2) is True
        assert opened.wait(timeout=2)
    finally:
        server.close()


@pytest.mark.parametrize("credential_type", ["google-oauth", "llm-api-key"])
def test_current_user_os__keyring_round_trip__uses_isolated_account(
    credential_type: str,
) -> None:
    store = OsKeyringSecretStoreAdapter(
        service_name=keyring_service_name(
            environment="development",
            credential_type=credential_type,
        )
    )
    account = f"installed-runtime-test-{uuid.uuid4().hex}"
    secret = f"isolated-{uuid.uuid4().hex}".encode()
    try:
        assert store.get(account) is None
        store.put(account, secret)
        assert store.get(account) == secret
        store.delete(account)
        assert store.get(account) is None
    finally:
        store.delete(account)
