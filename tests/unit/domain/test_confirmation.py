import pytest

from google_work_agent.domain import ResultCode, RunStatus
from google_work_agent.domain.confirmation import resume_confirmation
from google_work_agent.domain.exceptions import InvariantViolationError


def test_resume_confirmation_restores_requested_safe_status() -> None:
    result = resume_confirmation(
        RunStatus.WAITING_CONFIRMATION,
        current_version=7,
        expected_version=7,
        resume_status=RunStatus.PLANNING,
    )

    assert result.applied is True
    assert result.result_code is ResultCode.TRANSITION_APPLIED
    assert result.current_status is RunStatus.PLANNING
    assert result.current_version == 8


def test_resume_confirmation_rejects_version_conflict_without_transition() -> None:
    result = resume_confirmation(
        RunStatus.WAITING_CONFIRMATION,
        current_version=7,
        expected_version=6,
        resume_status=RunStatus.RETRIEVING,
    )

    assert result.applied is False
    assert result.result_code is ResultCode.VERSION_CONFLICT
    assert result.current_status is RunStatus.WAITING_CONFIRMATION
    assert result.current_version == 7


def test_resume_confirmation_rejects_non_waiting_state() -> None:
    result = resume_confirmation(
        RunStatus.ANALYZING,
        current_version=3,
        expected_version=3,
        resume_status=RunStatus.ANALYZING,
    )

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert result.current_status is RunStatus.ANALYZING


def test_resume_confirmation_rejects_unsafe_resume_status() -> None:
    with pytest.raises(InvariantViolationError, match="confirmation resume status"):
        resume_confirmation(
            RunStatus.WAITING_CONFIRMATION,
            current_version=1,
            expected_version=1,
            resume_status=RunStatus.WAITING_APPROVAL,
        )
