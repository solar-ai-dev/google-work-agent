"""Serve the closed current-user launcher control vocabulary over a Named Pipe."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
from collections.abc import Callable
from ctypes import wintypes
from multiprocessing.connection import PipeConnection, answer_challenge, deliver_challenge
from typing import Any

from launcher.acquire_single_instance import _current_user_identity

_MAX_REQUEST_BYTES = 256


class InstanceControlServer:
    def __init__(self, listener: Any, on_open_ui: Callable[[], None]) -> None:
        self._listener = listener
        self._on_open_ui = on_open_ui
        self._stopping = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="launcher-instance-control",
            daemon=True,
        )

    def start(self) -> InstanceControlServer:
        self._thread.start()
        return self

    def close(self) -> None:
        self._stopping.set()
        self._listener.close()
        self._thread.join(timeout=2)
        if self._thread.is_alive():
            raise OSError("instance control listener did not stop")

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                connection = self._listener.accept()
            except (OSError, EOFError):
                return
            try:
                request = connection.recv_bytes(_MAX_REQUEST_BYTES)
                payload = json.loads(request.decode("utf-8"))
                if payload == {"schema_version": 1, "command": "OPEN_UI"}:
                    try:
                        self._on_open_ui()
                    except Exception:
                        response = {"schema_version": 1, "status": "REJECTED"}
                    else:
                        response = {"schema_version": 1, "status": "ACCEPTED"}
                else:
                    response = {"schema_version": 1, "status": "REJECTED"}
                connection.send_bytes(
                    json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
            except (OSError, EOFError, UnicodeError, json.JSONDecodeError):
                pass
            finally:
                connection.close()


def serve_instance_control(
    control_endpoint: str,
    *,
    on_open_ui: Callable[[], None],
    listener_factory: Callable[[str, bytes], Any] | None = None,
) -> InstanceControlServer:
    """Start a listener that accepts only ``OPEN_UI`` and no business command."""

    _validate_endpoint(control_endpoint)
    factory = listener_factory or _create_listener
    listener = factory(control_endpoint, _control_authkey(control_endpoint))
    return InstanceControlServer(listener, on_open_ui).start()


class _CurrentUserPipeListener:
    """Windows Named Pipe listener with an explicit user+SYSTEM-only DACL."""

    def __init__(self, endpoint: str, authkey: bytes) -> None:
        if os.name != "nt":
            raise OSError("AF_PIPE is supported only on Windows")
        self._endpoint = endpoint
        self._authkey = authkey
        self._user_sid = _current_user_identity()
        self._pending_handle: int | None = None
        self._closed = False
        self._lock = threading.Lock()

    def accept(self) -> Any:
        handle = self._create_pipe()
        with self._lock:
            if self._closed:
                _close_handle(handle)
                raise OSError("listener is closed")
            self._pending_handle = handle
        kernel32 = _kernel32()
        connected = kernel32.ConnectNamedPipe(handle, None)
        if not connected and ctypes.get_last_error() != 535:  # ERROR_PIPE_CONNECTED
            with self._lock:
                self._pending_handle = None
            _close_handle(handle)
            raise ctypes.WinError(ctypes.get_last_error())
        with self._lock:
            self._pending_handle = None
        connection = PipeConnection(handle)
        try:
            # typeshed narrows these helpers to socket Connection even though AF_PIPE
            # PipeConnection implements the same challenge byte protocol on Windows.
            deliver_challenge(connection, self._authkey)  # type: ignore[arg-type]
            answer_challenge(connection, self._authkey)  # type: ignore[arg-type]
        except Exception:
            connection.close()
            raise
        return connection

    def close(self) -> None:
        with self._lock:
            self._closed = True
            handle = self._pending_handle
            self._pending_handle = None
        if handle is not None:
            _close_handle(handle)

    def _create_pipe(self) -> int:
        descriptor = ctypes.c_void_p()
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        )
        advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
        sddl = f"D:P(A;;GA;;;SY)(A;;GA;;;{self._user_sid})"
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = _SecurityAttributes(
            nLength=ctypes.sizeof(_SecurityAttributes),
            lpSecurityDescriptor=descriptor,
            bInheritHandle=False,
        )
        kernel32 = _kernel32()
        try:
            handle = kernel32.CreateNamedPipeW(
                self._endpoint,
                0x00000003,  # PIPE_ACCESS_DUPLEX
                0x00000004 | 0x00000002 | 0x00000008,  # message/read-message/reject-remote
                255,
                4_096,
                4_096,
                2_000,
                ctypes.byref(attributes),
            )
        finally:
            kernel32.LocalFree(descriptor)
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = (
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    )


def _create_listener(endpoint: str, authkey: bytes) -> _CurrentUserPipeListener:
    return _CurrentUserPipeListener(endpoint, authkey)


def _close_handle(handle: int) -> None:
    _kernel32().CloseHandle(handle)


def _kernel32() -> Any:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateNamedPipeW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
    )
    kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
    kernel32.ConnectNamedPipe.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    kernel32.ConnectNamedPipe.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    return kernel32


def _control_authkey(endpoint: str) -> bytes:
    return hashlib.sha256(f"GoogleWorkAgent-Control-v1|{endpoint}".encode()).digest()


def _validate_endpoint(endpoint: str) -> None:
    if not endpoint.startswith(r"\\.\pipe\GoogleWorkAgent-") or len(endpoint) > 128:
        raise ValueError("invalid launcher control endpoint")
