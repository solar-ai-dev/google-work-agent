"""Exact ownership smoke gate for the canonical Application module."""

from importlib import import_module


def test_canonical_application_owner_is_importable() -> None:
    module = import_module(
        "google_work_agent.application.use_cases.runtime_status.get_runtime_status"
    )

    assert module.__all__ == [
        "GetRuntimeStatusHandler",
        "GetRuntimeStatusQuery",
        "GetRuntimeStatusResult",
    ]
