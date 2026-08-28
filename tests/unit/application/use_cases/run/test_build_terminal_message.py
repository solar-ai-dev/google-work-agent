"""Exact ownership smoke gate for the canonical Application module."""

from importlib import import_module


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module("google_work_agent.application.use_cases.run.build_terminal_message")
        is not None
    )
