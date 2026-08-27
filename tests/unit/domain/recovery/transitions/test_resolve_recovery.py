import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.domain.recovery.transitions.resolve_recovery import (
    transition_resolve_recovery,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1


def test_recheck_unknown_result_to_executed_enters_verifying() -> None:
    decision = transition_resolve_recovery(
        RunStatusV1.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="UNKNOWN_RESULT",
        pre_recovery_status=RunStatusV1.WAITING_APPROVAL,
        recheck_input_changed=True,
        recovered_action_status=ActionStatusV1.EXECUTED,
    )

    assert decision.applied is True
    assert decision.current_status is RunStatusV1.VERIFYING


def test_recheck_unknown_result_to_failed_restores_pre_recovery_status() -> None:
    decision = transition_resolve_recovery(
        RunStatusV1.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="UNKNOWN_RESULT",
        pre_recovery_status=RunStatusV1.CANCEL_REQUESTED,
        recheck_input_changed=True,
        recovered_action_status=ActionStatusV1.FAILED,
    )

    assert decision.applied is True
    assert decision.current_status is RunStatusV1.CANCEL_REQUESTED


@pytest.mark.parametrize(
    "reason",
    ("UNKNOWN_RESULT", "VERIFICATION_MISMATCH", "CHECKPOINT_MISMATCH", "CONTRACT_VIOLATION"),
)
def test_same_input_recheck_stays_suspended(reason: str) -> None:
    decision = transition_resolve_recovery(
        RunStatusV1.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason=reason,  # type: ignore[arg-type]
        pre_recovery_status=RunStatusV1.WAITING_APPROVAL,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.NO_PROGRESS
    assert decision.current_status is RunStatusV1.RECOVERY_REQUIRED


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
        RunStatusV1.RECOVERY_REQUIRED,
        resolution=resolution,
        reason=reason,  # type: ignore[arg-type]
        pre_recovery_status=RunStatusV1.WAITING_APPROVAL,
        irrecoverable_confirmed=True,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.RESOLUTION_NOT_ALLOWED


def test_checkpoint_recheck_requires_validated_pre_recovery_status() -> None:
    decision = transition_resolve_recovery(
        RunStatusV1.RECOVERY_REQUIRED,
        resolution=RecoveryResolution.RECHECK,
        reason="CHECKPOINT_MISMATCH",
        pre_recovery_status=RunStatusV1.PLANNING,
        recheck_input_changed=True,
        validated_resume_status=RunStatusV1.RETRIEVING,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.NO_PROGRESS


def test_recheck_target_does_not_reapply() -> None:
    decision = transition_resolve_recovery(
        RunStatusV1.VERIFYING,
        resolution=RecoveryResolution.RECHECK,
        reason="VERIFICATION_MISMATCH",
        pre_recovery_status=RunStatusV1.WAITING_APPROVAL,
        recheck_input_changed=True,
    )

    assert decision.applied is False
    assert decision.result_code is ResultCode.STATE_CONFLICT
