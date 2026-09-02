import pytest

from google_work_agent.domain.run.model import (
    RunStatusV1,
    is_preempting_run_status,
    is_terminal_run_status,
)


@pytest.mark.parametrize(
    "status",
    (RunStatusV1.COMPLETED, RunStatusV1.BLOCKED, RunStatusV1.FAILED, RunStatusV1.CANCELLED),
)
def test_terminal_run__statuses_are__closed(status: RunStatusV1) -> None:
    assert is_terminal_run_status(status) is True


@pytest.mark.parametrize(
    "status",
    (RunStatusV1.CANCEL_REQUESTED, RunStatusV1.REAUTH_REQUIRED, RunStatusV1.RECOVERY_REQUIRED),
)
def test_preempting_statuses__block_normal__scheduler_progress(status: RunStatusV1) -> None:
    assert is_preempting_run_status(status) is True


def test_active_planning__status_is__not_preempting() -> None:
    assert is_terminal_run_status(RunStatusV1.PLANNING) is False
    assert is_preempting_run_status(RunStatusV1.PLANNING) is False
