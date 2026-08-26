import pytest

from google_work_agent.domain.enums import ActionStatus, RecoveryResolution, ResultCode, RunStatus
from google_work_agent.domain.recovery.transitions.resolve_recovery import (
    transition_resolve_recovery,
)


def test_recheck_unknown_result_to_executed_enters_verifying() -> None:
    decision = transition_resolve_recovery(
        RunStatus.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="UNKNOWN_RESULT",
        pre_recovery_status=RunStatus.WAITING_APPROVAL,
        recheck_input_changed=True,
        recovered_action_status=ActionStatus.EXECUTED,
    )

    assert decision.applied is True
    assert decision.current_status is RunStatus.VERIFYING


def test_recheck_unknown_result_to_failed_restores_pre_recovery_status() -> None:
    decision = transition_resolve_recovery(
        RunStatus.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="UNKNOWN_RESULT",
        pre_recovery_status=RunStatus.CANCEL_REQUESTED,
        recheck_input_changed=True,
        recovered_action_status=ActionStatus.FAILED,
    )

    assert decision.applied is True
    assert decision.current_status is RunStatus.CANCEL_REQUESTED


@pytest.mark.parametrize(
    "reason",
    ("UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"),
)
def test_same_input_recheck_stays_suspended(reason: str) -> None:
    decision = transition_resolve_recovery(
        RunStatus.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason=reason,  # type: ignore[arg-type]
        pre_recovery_status=RunStatus.WAITING_APPROVAL,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.NO_PROGRESS
    assert decision.current_status is RunStatus.RECOVERY_REQUIRED


@pytest.mark.parametrize(
    ("reason", "resolution"),
    (
        ("UNKNOWN_RESULT", RecoveryResolution.ACCEPT_PARTIAL),
        ("UNKNOWN_RESULT", RecoveryResolution.CREATE_CORRECTIVE_PLAN),
        ("UNKNOWN_RESULT", RecoveryResolution.FAIL),
        ("CHECKPOINT_MISMATCH", RecoveryResolution.ACCEPT_PARTIAL),
        ("CHECKPOINT_MISMATCH", RecoveryResolution.CREATE_CORRECTIVE_PLAN),
        ("CONTRACT_VIOLATION", RecoveryResolution.ACCEPT_PARTIAL),
        ("CONTRACT_VIOLATION", RecoveryResolution.CREATE_CORRECTIVE_PLAN),
    ),
)
def test_reason_resolution_matrix_rejects_forbidden_combinations(
    reason: str, resolution: RecoveryResolution
) -> None:
    decision = transition_resolve_recovery(
        RunStatus.RECOVERY_REQUIRED,
        resolution=resolution,
        reason=reason,  # type: ignore[arg-type]
        pre_recovery_status=RunStatus.WAITING_APPROVAL,
        irrecoverable_confirmed=True,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.RESOLUTION_NOT_ALLOWED


def test_checkpoint_recheck_requires_validated_pre_recovery_status() -> None:
    decision = transition_resolve_recovery(
        RunStatus.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="CHECKPOINT_MISMATCH",
        pre_recovery_status=RunStatus.PLANNING,
        recheck_input_changed=True,
        validated_resume_status=RunStatus.RETRIEVING,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.NO_PROGRESS


def test_recheck_target_does_not_reapply() -> None:
    decision = transition_resolve_recovery(
        RunStatus.VERIFYING,
        resolution=RecoveryResolution.RECHECK,
        reason="VERIFICATION_MISMATCH",
        pre_recovery_status=RunStatus.WAITING_APPROVAL,
        recheck_input_changed=True,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.STATE_CONFLICT
