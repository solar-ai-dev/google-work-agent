import pytest

from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import (
    is_preempting_run_status,
    is_terminal_run_status,
)


@pytest.mark.parametrize(
    "status", (RunStatus.COMPLETED, RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.CANCELLED)
)
def test_terminal_run_statuses_are_closed(status: RunStatus) -> None:
    assert is_terminal_run_status(status) is True


@pytest.mark.parametrize(
    "status", (RunStatus.CANCEL_REQUESTED, RunStatus.REAUTH_REQUIRED, RunStatus.RECOVERY_REQUIRED)
)
def test_preempting_statuses_block_normal_scheduler_progress(status: RunStatus) -> None:
    assert is_preempting_run_status(status) is True


def test_active_planning_status_is_not_preempting() -> None:
    assert is_terminal_run_status(RunStatus.PLANNING) is False
    assert is_preempting_run_status(RunStatus.PLANNING) is False
