from __future__ import annotations

import inspect

import pytest
from tests.support.fakes import approved_model
from tests.support.llm_runtime import runtime_selection

from google_work_agent.adapters.system import windows_hardware_probe as probe_module
from google_work_agent.adapters.system.windows_hardware_probe import WindowsHardwareProbeAdapter
from google_work_agent.ports.llm.structured_inference_contracts import (
    AvailabilityState,
    ProbeResult,
)


class _OllamaProbe:
    def __init__(self) -> None:
        self.models: list[object] = []

    def probe(self, *, endpoint: str | None, approved_model: object) -> ProbeResult:
        assert endpoint == "http://127.0.0.1:11434"
        self.models.append(approved_model)
        return ProbeResult(
            AvailabilityState.AVAILABLE,
            metadata={"version": "1", "model_digest": "fixture"},
        )


def test_probe_has_no__constructor_fields_that__can_fabricate_hardware_eligibility() -> None:
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


def test_observed_hardware__remains_fail_closed__without_release_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe_module, "_physical_memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(probe_module, "_probe_gpu", lambda _timeout: ("gpu", 8 * 1024**3))
    monkeypatch.setattr(probe_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(probe_module.platform, "machine", lambda: "AMD64")

    profile = WindowsHardwareProbeAdapter(
        runtime_selection=runtime_selection(deployment_profile="LOCAL_CAPABLE"),
        ollama_probe=_OllamaProbe(),
    ).probe()

    assert profile.cpu_logical_cores == 8
    assert profile.ram_total_bytes == 16 * 1024**3
    assert profile.gpu_present is True
    assert profile.ollama_available is True
    assert profile.local_runtime_eligible is False


def test_release_gate__receives_only__observed_facts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe_module.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(probe_module, "_physical_memory_bytes", lambda: 16 * 1024**3)
    monkeypatch.setattr(probe_module, "_probe_gpu", lambda _timeout: ("gpu", 8 * 1024**3))
    monkeypatch.setattr(probe_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(probe_module.platform, "machine", lambda: "AMD64")
    ollama_probe = _OllamaProbe()
    model = approved_model()
    profile = WindowsHardwareProbeAdapter(
        runtime_selection=runtime_selection(deployment_profile="LOCAL_CAPABLE", model=model),
        ollama_probe=ollama_probe,
    ).probe()

    assert ollama_probe.models == [model]
    assert profile.cpu_logical_cores == 8
    assert profile.ram_total_bytes == 16 * 1024**3
    assert profile.vram_total_bytes == 8 * 1024**3
    assert profile.local_runtime_eligible is True
