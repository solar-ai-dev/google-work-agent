"""Windows hardware discovery for the local-runtime eligibility boundary."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1

type LocalRuntimeEligibilityGate = Callable[[int, int, bool, int | None, bool, str | None], bool]


@dataclass(frozen=True, slots=True)
class WindowsHardwareProbeAdapter:
    """Report observed facts and apply an explicit release-owned gate.

    Absence or failure of the release gate is deliberately ineligible. Probe
    failures never fabricate a capable device or a positive RAM value.
    """

    ollama_endpoint: Callable[[], str | None] = field(
        default=lambda: "http://127.0.0.1:11434", repr=False
    )
    eligibility_gate: LocalRuntimeEligibilityGate | None = field(default=None, repr=False)
    probe_timeout_seconds: float = 1.0

    def probe(self) -> HardwareProfileV1:
        cpu_logical_cores = os.cpu_count()
        if cpu_logical_cores is None or cpu_logical_cores < 1:
            raise RuntimeError("HARDWARE_CPU_PROBE_UNAVAILABLE")
        ram_total_bytes = _physical_memory_bytes()
        gpu_name, vram_total_bytes = _probe_gpu(self.probe_timeout_seconds)
        gpu_present = gpu_name is not None
        ollama_available, ollama_version = _probe_ollama(
            self.ollama_endpoint(), self.probe_timeout_seconds
        )
        eligible = bool(
            self.eligibility_gate
            and self.eligibility_gate(
                cpu_logical_cores,
                ram_total_bytes,
                gpu_present,
                vram_total_bytes,
                ollama_available,
                ollama_version,
            )
        )
        return HardwareProfileV1(
            schema_version=1,
            cpu_logical_cores=cpu_logical_cores,
            ram_total_bytes=ram_total_bytes,
            gpu_present=gpu_present,
            gpu_name=gpu_name,
            vram_total_bytes=vram_total_bytes,
            ollama_available=ollama_available,
            ollama_version=ollama_version,
            local_runtime_eligible=eligible,
        )


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _physical_memory_bytes() -> int:
    if os.name == "nt":
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(status)
        windows_api = vars(ctypes).get("windll")
        if windows_api is None:
            raise RuntimeError("HARDWARE_RAM_PROBE_UNAVAILABLE")
        if not windows_api.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError("HARDWARE_RAM_PROBE_UNAVAILABLE")
        total = int(status.ullTotalPhys)
    else:
        sysconf_value = vars(os).get("sysconf")
        if not callable(sysconf_value):
            raise RuntimeError("HARDWARE_RAM_PROBE_UNAVAILABLE")
        sysconf = cast(Callable[[str], int], sysconf_value)
        total = int(sysconf("SC_PAGE_SIZE")) * int(sysconf("SC_PHYS_PAGES"))
    if total <= 0:
        raise RuntimeError("HARDWARE_RAM_PROBE_UNAVAILABLE")
    return total


def _probe_gpu(timeout_seconds: float) -> tuple[str | None, int | None]:
    if os.name != "nt":
        return None, None
    command = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
    )
    creation_flags = cast(int, getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            check=True,
            text=True,
            timeout=max(0.1, timeout_seconds),
            creationflags=creation_flags,
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None, None
    devices = payload if isinstance(payload, list) else [payload]
    candidates = [item for item in devices if isinstance(item, dict) and item.get("Name")]
    if not candidates:
        return None, None
    device = max(candidates, key=lambda item: int(item.get("AdapterRAM") or 0))
    raw_vram = device.get("AdapterRAM")
    vram = int(raw_vram) if isinstance(raw_vram, int) and raw_vram > 0 else None
    return str(device["Name"]), vram


def _probe_ollama(endpoint: str | None, timeout_seconds: float) -> tuple[bool, str | None]:
    if endpoint is None:
        return False, None
    parsed = urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return False, None
    try:
        with urlopen(  # nosec B310 - endpoint is validated loopback-only above
            Request(f"{endpoint.rstrip('/')}/api/version", method="GET"),
            timeout=max(0.1, timeout_seconds),
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False, None
    version = payload.get("version") if isinstance(payload, dict) else None
    return True, version if isinstance(version, str) and version.strip() else None


__all__ = ["LocalRuntimeEligibilityGate", "WindowsHardwareProbeAdapter"]
