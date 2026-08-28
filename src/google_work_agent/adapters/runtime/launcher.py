"""Launcher state machine and Windows-facing runtime ports."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class LauncherState(StrEnum):
    STOPPED = "STOPPED"
    VALIDATING_ARTIFACTS = "VALIDATING_ARTIFACTS"
    ACQUIRING_INSTANCE = "ACQUIRING_INSTANCE"
    STARTING_SERVICE = "STARTING_SERVICE"
    WAITING_LIVE = "WAITING_LIVE"
    WAITING_READY = "WAITING_READY"
    OPENING_BROWSER = "OPENING_BROWSER"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    SAFE_MODE = "SAFE_MODE"
    START_FAILED = "START_FAILED"
    SHUTDOWN_TIMEOUT = "SHUTDOWN_TIMEOUT"


@dataclass(frozen=True, slots=True)
class LauncherStatus:
    state: LauncherState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class InstanceAcquireResult:
    acquired: bool
    existing_endpoint: str | None = None


class InstanceRegistry(Protocol):
    def acquire(self) -> InstanceAcquireResult: ...
    def release(self) -> None: ...
    def open_existing_ui(self, endpoint: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ServiceLaunchRequest:
    executable_path: str
    host: str
    port: int


class ServiceProcessHandle(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...


class ServiceProcessLauncher(Protocol):
    def launch(self, request: ServiceLaunchRequest) -> ServiceProcessHandle: ...


@dataclass(frozen=True, slots=True)
class BrowserLaunchRequest:
    url: str


class BrowserLauncher(Protocol):
    def open(self, request: BrowserLaunchRequest) -> bool: ...


class LauncherPort(Protocol):
    def wait_live(self, *, host: str, port: int, timeout_seconds: float) -> bool: ...
    def wait_ready(self, *, host: str, port: int, timeout_seconds: float) -> str: ...


class DynamicLoopbackPortAllocator:
    def allocate(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            return int(server.getsockname()[1])


class LauncherCore:
    def __init__(
        self,
        *,
        instance_registry: InstanceRegistry,
        port_allocator: DynamicLoopbackPortAllocator,
        service_launcher: ServiceProcessLauncher,
        health_port: LauncherPort,
        browser_launcher: BrowserLauncher,
        service_executable_path: str,
    ) -> None:
        self._instance_registry = instance_registry
        self._port_allocator = port_allocator
        self._service_launcher = service_launcher
        self._health_port = health_port
        self._browser_launcher = browser_launcher
        self._service_executable_path = service_executable_path
        self._service_handle: ServiceProcessHandle | None = None
        self.status = LauncherStatus(LauncherState.STOPPED)

    def start(self) -> LauncherStatus:
        self.status = LauncherStatus(LauncherState.VALIDATING_ARTIFACTS)
        self.status = LauncherStatus(LauncherState.ACQUIRING_INSTANCE)
        instance = self._instance_registry.acquire()
        if not instance.acquired:
            if instance.existing_endpoint is not None:
                self._instance_registry.open_existing_ui(instance.existing_endpoint)
            self.status = LauncherStatus(LauncherState.RUNNING, detail="existing_instance")
            return self.status
        port = self._port_allocator.allocate()
        self.status = LauncherStatus(LauncherState.STARTING_SERVICE)
        self._service_handle = self._service_launcher.launch(
            ServiceLaunchRequest(
                executable_path=self._service_executable_path,
                host="127.0.0.1",
                port=port,
            )
        )
        self.status = LauncherStatus(LauncherState.WAITING_LIVE)
        if not self._health_port.wait_live(host="127.0.0.1", port=port, timeout_seconds=30):
            self.status = LauncherStatus(LauncherState.START_FAILED, detail="live timeout")
            return self.status
        self.status = LauncherStatus(LauncherState.WAITING_READY)
        ready_state = self._health_port.wait_ready(host="127.0.0.1", port=port, timeout_seconds=30)
        if ready_state == "SAFE_MODE":
            self.status = LauncherStatus(LauncherState.SAFE_MODE)
            return self.status
        if ready_state != "READY":
            self.status = LauncherStatus(LauncherState.START_FAILED, detail=ready_state)
            return self.status
        self.status = LauncherStatus(LauncherState.OPENING_BROWSER)
        opened = self._browser_launcher.open(BrowserLaunchRequest(url=f"http://127.0.0.1:{port}/"))
        if not opened:
            self.status = LauncherStatus(LauncherState.RUNNING, detail="browser_unavailable")
            return self.status
        self.status = LauncherStatus(LauncherState.RUNNING)
        return self.status

    def stop(self) -> LauncherStatus:
        self.status = LauncherStatus(LauncherState.STOPPING)
        if self._service_handle is not None:
            self._service_handle.terminate()
        self._instance_registry.release()
        self.status = LauncherStatus(LauncherState.STOPPED)
        return self.status
