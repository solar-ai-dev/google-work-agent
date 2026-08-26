"""Canonical hardware-probe adapter placement."""

from google_work_agent.adapters.llm.probes import (
    DefaultHardwareProbe as WindowsHardwareProbeAdapter,
)

__all__ = ["WindowsHardwareProbeAdapter"]
