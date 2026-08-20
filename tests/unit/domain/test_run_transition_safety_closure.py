import pytest

from google_work_agent.domain import (
    InvariantViolationError,
    RecoveryResolution,
    RunCommand,
    RunStatus,
    transition_run,
)


def test_waiting_confirmation_cannot_bypass_resume_confirmation_with_begin_retrieval() -> None:
    result = transition_run(
        RunStatus.WAITING_CONFIRMATION,
        RunCommand.BEGIN_RETRIEVAL,
        current_version=2,
        expected_version=2,
    )

    assert result.applied is False
    assert result.current_status is RunStatus.WAITING_CONFIRMATION


@pytest.mark.parametrize("status", [RunStatus.CREATED, RunStatus.WAITING_CONFIRMATION])
def test_block_run_has_created_and_waiting_confirmation_parity(status: RunStatus) -> None:
    result = transition_run(
        status,
        RunCommand.BLOCK_RUN,
        current_version=2,
        expected_version=2,
    )

    assert result.applied is True
    assert result.current_status is RunStatus.BLOCKED


def test_resolve_recovery_uses_registered_variant_mapping() -> None:
    result = transition_run(
        RunStatus.RECOVERY_REQUIRED,
        RunCommand.RESOLVE_RECOVERY,
        current_version=3,
        expected_version=3,
        recovery_resolution=RecoveryResolution.RECHECK,
    )

    assert result.applied is True
    assert result.current_status is RunStatus.VERIFYING


def test_resolve_recovery_rejects_arbitrary_compatibility_target() -> None:
    with pytest.raises(InvariantViolationError, match="registered recovery variant"):
        transition_run(
            RunStatus.RECOVERY_REQUIRED,
            RunCommand.RESOLVE_RECOVERY,
            current_version=3,
            expected_version=3,
            recovery_next_status=RunStatus.ANALYZING,
        )
