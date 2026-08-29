from __future__ import annotations

import inspect

import pytest

from google_work_agent.adapters.system import windows_hardware_probe as probe_module
from google_work_agent.adapters.system.windows_hardware_probe import WindowsHardwareProbeAdapter


def test_probe_has_no_constructor_fields_that_can_fabricate_hardware_eligibility() -> None:
    parameters = inspect.signature(WindowsHardwareProbeAdapter).parameters
    assert {
        "ram_total_bytes",
        "gpu_present",
        "gpu_name",
        "vram_total_bytes",
        "ollama_available",
        "ollama_version",
        "local_runtime_eligible",
    }.isdisjoint(parameters)


def test_observed_hardware_remains_fail_closed_without_release_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe_module, "_physical_memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(probe_module, "_probe_gpu", lambda _timeout: ("gpu", 8 * 1024**3))
    monkeypatch.setattr(probe_module, "_probe_ollama", lambda _endpoint, _timeout: (True, "1"))

    profile = WindowsHardwareProbeAdapter().probe()

    assert profile.cpu_logical_cores == 8
    assert profile.ram_total_bytes == 16 * 1024**3
    assert profile.gpu_present is True
    assert profile.ollama_available is True
    assert profile.local_runtime_eligible is False


def test_release_gate_receives_only_observed_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe_module, "_physical_memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(probe_module, "_probe_gpu", lambda _timeout: ("gpu", 8 * 1024**3))
    monkeypatch.setattr(probe_module, "_probe_ollama", lambda _endpoint, _timeout: (True, "1"))
    observed: list[tuple[object, ...]] = []

    def gate(*facts: object) -> bool:
        observed.append(facts)
        return True

    profile = WindowsHardwareProbeAdapter(eligibility_gate=gate).probe()

    assert observed == [(8, 16 * 1024**3, True, 8 * 1024**3, True, "1")]
    assert profile.local_runtime_eligible is True
