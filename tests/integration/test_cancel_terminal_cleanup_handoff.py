"""Pending Integration-owned cancellation terminal cleanup contract."""

from __future__ import annotations

import inspect

import pytest

from google_work_agent.application.coordinator import LocalRunCoordinator


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CROSS_AGENT_DEPENDENCY: Integration must call runtime.discard_run_transients(run_id) "
        "after an applied CANCELLED FinalizeRunCancellation response"
    ),
)
def test_cancel_terminal_caller_invokes_run_scoped_transient_cleanup() -> None:
    """Turn green only when Integration wires the already-implemented runtime hook."""
    source = inspect.getsource(LocalRunCoordinator._continue_cancellation)

    assert "discard_run_transients" in source
