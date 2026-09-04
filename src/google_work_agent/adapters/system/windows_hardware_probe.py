"""Windows hardware discovery for the local-runtime eligibility boundary."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from google_work_agent.adapters.llm.runtime.evaluate_local_runtime_eligibility import (
    evaluate_local_runtime_eligibility,
)
from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    OllamaRuntimeProbe,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1


@dataclass(frozen=True, slots=True)
class WindowsHardwareProbeAdapter:
    """Report observed facts and apply an explicit release-owned gate.

    Absence or failure of the release gate is deliberately ineligible. Probe
    failures never fabricate a capable device or a positive RAM value.
    """

    runtime_selection: LlmRuntimeSelectionV1
    ollama_probe: OllamaRuntimeProbe
    probe_timeout_seconds: float = 1.0
    selected_model_provider: Callable[[], ApprovedModelInfo | None] | None = None

    def probe(self) -> HardwareProfileV1:
        cpu_logical_cores = os.cpu_count()
        if cpu_logical_cores is None or cpu_logical_cores < 1:
            raise RuntimeError("HARDWARE_CPU_PROBE_UNAVAILABLE")
        ram_total_bytes = _physical_memory_bytes()
        gpu_name, vram_total_bytes = _probe_gpu(self.probe_timeout_seconds)
        gpu_present = gpu_name is not None
        operating_system = platform.system().upper()
        architecture = platform.machine().upper()
        probe = self.ollama_probe.probe(
            endpoint=self.runtime_selection.ollama_endpoint,
            approved_model=(
                self.runtime_selection.selected_model
                if self.selected_model_provider is None
                else self.selected_model_provider()
            ),
        )
        decision = evaluate_local_runtime_eligibility(
            runtime_selection=self.runtime_selection,
            operating_system=operating_system,
            architecture=architecture,
            cpu_logical_cores=cpu_logical_cores,
            ram_total_bytes=ram_total_bytes,
            gpu_present=gpu_present,
            vram_total_bytes=vram_total_bytes,
            ollama_probe=probe,
        )
        raw_version = probe.metadata.get("version")
        ollama_version = raw_version if isinstance(raw_version, str) else None
        return HardwareProfileV1(
            schema_version=1,
            cpu_logical_cores=cpu_logical_cores,
            ram_total_bytes=ram_total_bytes,
            gpu_present=gpu_present,
            gpu_name=gpu_name,
            vram_total_bytes=vram_total_bytes,
            ollama_available=probe.availability.value == "AVAILABLE",
            ollama_version=ollama_version,
            local_runtime_eligible=decision.eligible,
            operating_system=operating_system,
            architecture=architecture,
            local_runtime_reason_codes=decision.safe_reason_codes,
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
    nvidia = _probe_nvidia_gpu(timeout_seconds)
    if nvidia != (None, None):
        return nvidia
    return _probe_wmi_gpu(timeout_seconds)


def _probe_nvidia_gpu(timeout_seconds: float) -> tuple[str | None, int | None]:
    creation_flags = cast(int, getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            text=True,
            timeout=max(0.1, timeout_seconds),
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    candidates: list[tuple[str, int]] = []
    for line in completed.stdout.splitlines():
        name, separator, raw_memory = line.rpartition(",")
        try:
            memory_mib = int(raw_memory.strip())
        except ValueError:
            continue
        if separator and name.strip() and memory_mib > 0:
            candidates.append((name.strip(), memory_mib * 1024**2))
    return max(candidates, key=lambda item: item[1], default=(None, None))


def _probe_wmi_gpu(timeout_seconds: float) -> tuple[str | None, int | None]:
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


__all__ = ["WindowsHardwareProbeAdapter"]
