"""Own current-user single-instance acquisition and stale-lock adjudication."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

_LOCK_FIELDS = {
    "schema_version",
    "owner_user_hash",
    "launcher_pid",
    "launcher_process_token",
    "service_instance_id",
    "control_endpoint",
    "acquired_at_ms",
}


class SingleInstanceError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class SingleInstanceLease:
    acquired: bool
    lock_path: Path
    control_endpoint: str
    owner_user_hash: str
    launcher_pid: int | None = None
    launcher_process_token: str | None = None
    service_instance_id: str | None = None

    def bind_service_instance(self, service_instance_id: str) -> SingleInstanceLease:
        if not self.acquired or self.launcher_pid is None or self.launcher_process_token is None:
            raise SingleInstanceError("SINGLE_INSTANCE_NOT_OWNED")
        updated = replace(self, service_instance_id=service_instance_id)
        _write_owned_lock(updated)
        return updated

    def release(self) -> None:
        if not self.acquired or not self.lock_path.is_file():
            return
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if (
            payload.get("owner_user_hash") == self.owner_user_hash
            and payload.get("launcher_pid") == self.launcher_pid
            and payload.get("launcher_process_token") == self.launcher_process_token
        ):
            self.lock_path.unlink(missing_ok=True)


def acquire_single_instance(
    runtime_dir: Path,
    *,
    user_identity: str | None = None,
    process_identity: Callable[[int], str | None] | None = None,
    now_ms: int | None = None,
    max_attempts: int = 4,
) -> SingleInstanceLease:
    """Atomically acquire ``service.lock`` or return the trustworthy live endpoint."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    runtime = runtime_dir.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    lock_path = runtime / "service.lock"
    identity = user_identity or _current_user_identity()
    owner_user_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    endpoint = rf"\\.\pipe\GoogleWorkAgent-{owner_user_hash[:24]}"
    resolve_process = process_identity or _process_identity
    launcher_pid = os.getpid()
    launcher_token = resolve_process(launcher_pid)
    if launcher_token is None:
        raise SingleInstanceError("PROCESS_IDENTITY_UNAVAILABLE")

    payload = {
        "schema_version": 1,
        "owner_user_hash": owner_user_hash,
        "launcher_pid": launcher_pid,
        "launcher_process_token": launcher_token,
        "service_instance_id": None,
        "control_endpoint": endpoint,
        "acquired_at_ms": now_ms if now_ms is not None else time.time_ns() // 1_000_000,
    }
    for _attempt in range(max_attempts):
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                existing, stat_before = _read_existing_lock(lock_path)
            except FileNotFoundError:
                continue
            if existing.get("owner_user_hash") != owner_user_hash:
                raise SingleInstanceError("SINGLE_INSTANCE_USER_MISMATCH") from None
            existing_pid = existing.get("launcher_pid")
            existing_token = existing.get("launcher_process_token")
            existing_endpoint = existing.get("control_endpoint")
            if (
                not isinstance(existing_pid, int)
                or existing_pid <= 0
                or not isinstance(existing_token, str)
                or not isinstance(existing_endpoint, str)
                or not existing_endpoint.startswith(r"\\.\pipe\GoogleWorkAgent-")
                or len(existing_endpoint) > 128
            ):
                raise SingleInstanceError("SINGLE_INSTANCE_LOCK_UNTRUSTED") from None
            if resolve_process(existing_pid) == existing_token:
                return SingleInstanceLease(
                    acquired=False,
                    lock_path=lock_path,
                    control_endpoint=existing_endpoint,
                    owner_user_hash=owner_user_hash,
                    service_instance_id=_optional_string(existing.get("service_instance_id")),
                )
            _remove_stale_lock(
                lock_path,
                expected_stat=stat_before,
                expected_pid=existing_pid,
                expected_token=existing_token,
                process_identity=resolve_process,
            )
            continue
        except OSError as error:
            raise SingleInstanceError("SINGLE_INSTANCE_CONFLICT") from error
        try:
            encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            os.write(descriptor, encoded)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return SingleInstanceLease(
            acquired=True,
            lock_path=lock_path,
            control_endpoint=endpoint,
            owner_user_hash=owner_user_hash,
            launcher_pid=launcher_pid,
            launcher_process_token=launcher_token,
        )
    raise SingleInstanceError("SINGLE_INSTANCE_CONFLICT")


def _write_owned_lock(lease: SingleInstanceLease) -> None:
    payload = {
        "schema_version": 1,
        "owner_user_hash": lease.owner_user_hash,
        "launcher_pid": lease.launcher_pid,
        "launcher_process_token": lease.launcher_process_token,
        "service_instance_id": lease.service_instance_id,
        "control_endpoint": lease.control_endpoint,
        "acquired_at_ms": time.time_ns() // 1_000_000,
    }
    temporary = lease.lock_path.with_name(".service.lock.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, lease.lock_path)


def _read_existing_lock(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    try:
        stat_before = path.stat()
        if stat_before.st_size > 2_048:
            raise SingleInstanceError("SINGLE_INSTANCE_LOCK_UNTRUSTED")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except (OSError, json.JSONDecodeError) as error:
        raise SingleInstanceError("SINGLE_INSTANCE_LOCK_UNTRUSTED") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != _LOCK_FIELDS
        or payload.get("schema_version") != 1
    ):
        raise SingleInstanceError("SINGLE_INSTANCE_LOCK_UNTRUSTED")
    return payload, stat_before


def _same_file_version(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) == (
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )


def _remove_stale_lock(
    lock_path: Path,
    *,
    expected_stat: os.stat_result,
    expected_pid: int,
    expected_token: str,
    process_identity: Callable[[int], str | None],
) -> None:
    guard_path = lock_path.with_name("service.lock.stale-guard")
    try:
        descriptor = os.open(guard_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        time.sleep(0.01)
        return
    try:
        try:
            payload, current_stat = _read_existing_lock(lock_path)
        except FileNotFoundError:
            return
        unchanged = (
            _same_file_version(expected_stat, current_stat)
            and payload.get("launcher_pid") == expected_pid
            and payload.get("launcher_process_token") == expected_token
        )
        if unchanged and process_identity(expected_pid) != expected_token:
            lock_path.unlink(missing_ok=True)
    finally:
        os.close(descriptor)
        guard_path.unlink(missing_ok=True)


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _current_user_identity() -> str:
    if os.name != "nt":
        raise SingleInstanceError("UNSUPPORTED_OS")
    try:
        output = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise SingleInstanceError("CURRENT_USER_UNAVAILABLE") from error
    match = re.search(r"S-1-[0-9-]+", output)
    if match is None:
        raise SingleInstanceError("CURRENT_USER_UNAVAILABLE")
    return match.group(0)


def _process_identity(process_id: int) -> str | None:
    if process_id <= 0:
        return None
    if os.name != "nt":
        return None
    process_query_limited_information = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, process_id)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        creation_value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"{process_id}:{creation_value}"
    finally:
        kernel32.CloseHandle(handle)
