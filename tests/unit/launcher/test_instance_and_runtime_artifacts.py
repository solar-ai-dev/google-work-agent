from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path

from launcher.acquire_single_instance import acquire_single_instance
from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.create_service_instance_id import create_service_instance_id
from launcher.prepare_data_directory import prepare_data_directory


def test_single_instance_is__atomic_and_live__owner_is_reused(tmp_path: Path) -> None:
    def process_identity(process_id: int) -> str:
        return f"token-{process_id}"

    first = acquire_single_instance(
        tmp_path,
        user_identity="S-1-5-21-test",
        process_identity=process_identity,
        now_ms=10,
    )
    second = acquire_single_instance(
        tmp_path,
        user_identity="S-1-5-21-test",
        process_identity=process_identity,
        now_ms=11,
    )

    assert first.acquired is True
    assert second.acquired is False
    assert second.control_endpoint == first.control_endpoint
    first.release()
    assert not (tmp_path / "service.lock").exists()


def test_stale_lock__is_adjudicated_before__new_owner_acquires(tmp_path: Path) -> None:
    lock_path = tmp_path / "service.lock"
    lock_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "owner_user_hash": hashlib.sha256(b"S-1-5-21-test").hexdigest(),
                "launcher_pid": 999_999,
                "launcher_process_token": "stale-token",
                "service_instance_id": "old-instance",
                "control_endpoint": r"\\.\pipe\GoogleWorkAgent-stale",
                "acquired_at_ms": 1,
            }
        ),
        encoding="utf-8",
    )

    lease = acquire_single_instance(
        tmp_path,
        user_identity="S-1-5-21-test",
        process_identity=lambda process_id: (
            f"token-{process_id}" if process_id == os.getpid() else None
        ),
    )

    assert lease.acquired is True
    assert not (tmp_path / "service.lock.stale-guard").exists()
    lease.release()


def test_data_layout_and__runtime_metadata_are__exact_and_secret_free(tmp_path: Path) -> None:
    acl_calls: list[Path] = []
    layout = prepare_data_directory(tmp_path, acl_initializer=acl_calls.append)
    reservation = allocate_dynamic_port()
    identity = create_service_instance_id(
        layout.runtime_dir,
        host="127.0.0.1",
        port=reservation.port,
        control_endpoint=r"\\.\pipe\GoogleWorkAgent-current-user",
        now_ms=123,
    ).bind_service_pid(456)

    payload = json.loads(layout.service_instance_path.read_text(encoding="utf-8"))
    assert acl_calls == [tmp_path.resolve()]
    assert payload == {
        "schema_version": 1,
        "service_instance_id": identity.service_instance_id,
        "launcher_pid": os.getpid(),
        "service_pid": 456,
        "host": "127.0.0.1",
        "port": reservation.port,
        "control_endpoint": r"\\.\pipe\GoogleWorkAgent-current-user",
        "started_at_ms": 123,
    }
    assert "secret" not in layout.service_instance_path.read_text(encoding="utf-8").lower()
    assert layout.service_lock_path == layout.runtime_dir / "service.lock"
    assert layout.shutdown_marker_path == layout.runtime_dir / "shutdown.marker"
    assert layout.attachment_cache_dir == layout.root / "cache" / "attachments"

    identity.clear()
    reservation.release()
    assert not layout.service_instance_path.exists()


def test_dynamic_port__is_loopback_reserved__until_explicit_release() -> None:
    reservation = allocate_dynamic_port()
    competing = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            competing.bind(("127.0.0.1", reservation.port))
        except OSError:
            pass
        else:
            raise AssertionError("reserved port was concurrently bindable")
    finally:
        competing.close()

    port = reservation.port
    reservation.release()
    rebound = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        rebound.bind(("127.0.0.1", port))
    finally:
        rebound.close()
