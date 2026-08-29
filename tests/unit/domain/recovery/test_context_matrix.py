from __future__ import annotations

import pytest

from google_work_agent.domain.recovery.model import validate_recovery_context_shape


def test_unknown_result_requires_action_and_attempt_without_verification() -> None:
    validate_recovery_context_shape(
        reason="UNKNOWN_RESULT",
        scope="ACTION",
        recovery_fingerprint="fp",
        action_id="action-1",
        execution_attempt_id="attempt-1",
        verification_id=None,
        registered_resume_target_present=False,
        observed_external_state_fingerprint=None,
        verification_input_fingerprint=None,
        contract_or_checkpoint_fingerprint=None,
    )


@pytest.mark.parametrize(
    ("reason", "scope"),
    [("UNKNOWN_RESULT", "RUN"), ("VERIFICATION_MISMATCH", "RUN")],
)
def test_action_reasons_reject_run_scope(reason: str, scope: str) -> None:
    with pytest.raises(ValueError):
        validate_recovery_context_shape(
            reason=reason,  # type: ignore[arg-type]
            scope=scope,
            recovery_fingerprint="fp",
            action_id=None,
            execution_attempt_id=None,
            verification_id=None,
            registered_resume_target_present=False,
            observed_external_state_fingerprint=None,
            verification_input_fingerprint=None,
            contract_or_checkpoint_fingerprint=None,
        )


def test_checkpoint_mismatch_requires_registered_target_and_fingerprint() -> None:
    with pytest.raises(ValueError, match="registered resume target"):
        validate_recovery_context_shape(
            reason="CHECKPOINT_MISMATCH",
            scope="RUN",
            recovery_fingerprint="fp",
            action_id=None,
            execution_attempt_id=None,
            verification_id=None,
            registered_resume_target_present=False,
            observed_external_state_fingerprint=None,
            verification_input_fingerprint=None,
            contract_or_checkpoint_fingerprint="checkpoint-fp",
        )


def test_unknown_result_rejects_foreign_reason_fingerprints() -> None:
    with pytest.raises(ValueError, match="foreign reason facts"):
        validate_recovery_context_shape(
            reason="UNKNOWN_RESULT",
            scope="ACTION",
            recovery_fingerprint="fp",
            action_id="action-1",
            execution_attempt_id="attempt-1",
            verification_id=None,
            registered_resume_target_present=False,
            observed_external_state_fingerprint="mismatch-only",
            verification_input_fingerprint=None,
            contract_or_checkpoint_fingerprint=None,
        )
