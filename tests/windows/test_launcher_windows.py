from __future__ import annotations

from google_work_agent.adapters.runtime import DynamicLoopbackPortAllocator


def test_dynamic_loopback_port_allocator_returns_positive_port() -> None:
    port = DynamicLoopbackPortAllocator().allocate()

    assert port > 0
