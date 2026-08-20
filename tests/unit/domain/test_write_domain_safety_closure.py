from __future__ import annotations

import pytest

from google_work_agent.application.cancel_intent import is_applied_request_cancel_receipt
from google_work_agent.domain import (
    InvariantViolationError,
    RecoveryResolution,
    ResultCode,
    RunCommand,
    RunStatus,
    transition_run,
)
from google_work_agent.domain.claim_contract import (
    CLAIM_CONTEXT_DEFAULT_TTL_MS,
    CLAIM_CONTEXT_MAX_TTL_MS,
    validate_claim_ttl_ms,
)


def test_claim_ttl_is_short_lived_and_bounded_independently() -> None:
    assert CLAIM_CONTEXT_DEFAULT_TTL_MS == 30_000
    assert CLAIM_CONTEXT_MAX_TTL_MS == 60_000
    assert validate_claim_ttl_ms(CLAIM_CONTEXT_DEFAULT_TTL_MS) == 30_000
    with pytest.raises(ValueError):
        validate_claim_ttl_ms(CLAIM_CONTEXT_MAX_TTL_MS + 1)


def test_waiting_confirmation_cannot_bypass_resume_confirmation() -> None:
    result = transition_run(
        RunStatus.WAITING_CONFIRMATION,
        RunCommand.BEGIN_RETRIEVAL,
        current_version=2,
        expected_version=2,
    )
    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert RunCommand.RESUME_CONFIRMATION in result.next_allowed_commands


def test_block_run_parity_includes_created_and_waiting_confirmation() -> None:
    for status in (RunStatus.CREATED, RunStatus.WAITING_CONFIRMATION):
        result = transition_run(
            status,
            RunCommand.BLOCK_RUN,
            current_version=1,
            expected_version=1,
        )
        assert result.applied is True
        assert result.current_status is RunStatus.BLOCKED


def test_recovery_registered_variant_maps_to_canonical_target() -> None:
    result = transition_run(
        RunStatus.RECOVERY_REQUIRED,
        RunCommand.RESOLVE_RECOVERY,
        current_version=5,
        expected_version=5,
        recovery_resolution=RecoveryResolution.RECHECK,
    )
    assert result.applied is True
    assert result.current_status is RunStatus.VERIFYING


def test_recovery_arbitrary_raw_target_fails_closed() -> None:
    with pytest.raises(InvariantViolationError):
        transition_run(
            RunStatus.RECOVERY_REQUIRED,
            RunCommand.RESOLVE_RECOVERY,
            current_version=5,
            expected_version=5,
            recovery_next_status=RunStatus.ANALYZING,
        )


def test_cancel_intent_requires_applied_request_cancel_receipt() -> None:
    assert is_applied_request_cancel_receipt(
        command_type="RequestRunCancellation",
        aggregate_type="Run",
        aggregate_id="run-1",
        status="APPLIED",
        result_code=ResultCode.TRANSITION_APPLIED.value,
        run_id="run-1",
    )
    assert not is_applied_request_cancel_receipt(
        command_type="RequestRunCancellation",
        aggregate_type="Run",
        aggregate_id="run-1",
        status="REJECTED",
        result_code=ResultCode.STATE_CONFLICT.value,
        run_id="run-1",
    )
    assert not is_applied_request_cancel_receipt(
        command_type="SomeAuditLikeCommand",
        aggregate_type="Run",
        aggregate_id="run-1",
        status="APPLIED",
        result_code=ResultCode.TRANSITION_APPLIED.value,
        run_id="run-1",
    )
