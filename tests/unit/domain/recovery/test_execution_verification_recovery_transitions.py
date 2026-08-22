import pytest

from google_work_agent.domain.action.model import ActionCommand
from google_work_agent.domain.enums import ActionStatus, VerificationStatus
from google_work_agent.domain.exceptions import InvariantViolationError
from google_work_agent.domain.execution_attempt.transitions.mark_failed import transition_mark_failed
from google_work_agent.domain.execution_attempt.transitions.mark_unknown_result import transition_mark_unknown_result
from google_work_agent.domain.execution_attempt.transitions.store_success import transition_store_success
from google_work_agent.domain.recovery.transitions.prepare_write_retry import transition_prepare_write_retry
from google_work_agent.domain.recovery.transitions.recover_existing_result import transition_recover_existing_result
from google_work_agent.domain.recovery.transitions.resolve_as_failed import transition_resolve_as_failed
from google_work_agent.domain.verification.transitions.store_verification import transition_store_verification


def test_success_requires_executing_and_moves_to_executed():
    result = transition_store_success(ActionStatus.EXECUTING, current_version=3, expected_version=3)
    assert result.applied
    assert result.current_status is ActionStatus.EXECUTED
    assert result.next_allowed_commands == (ActionCommand.STORE_VERIFICATION,)


def test_failed_requires_not_sent():
    with pytest.raises(InvariantViolationError):
        transition_mark_failed(ActionStatus.EXECUTING, current_version=0, expected_version=0, delivery_certainty="MAY_HAVE_BEEN_SENT")


def test_unknown_result_cannot_become_retry_directly():
    unknown = transition_mark_unknown_result(ActionStatus.EXECUTING, current_version=0, expected_version=0)
    assert unknown.current_status is ActionStatus.UNKNOWN_RESULT
    assert ActionCommand.PREPARE_WRITE_RETRY not in unknown.next_allowed_commands


def test_unknown_result_recovered_existing_requires_verification():
    result = transition_recover_existing_result(ActionStatus.UNKNOWN_RESULT, current_version=1, expected_version=1)
    assert result.current_status is ActionStatus.EXECUTED
    assert result.next_allowed_commands == (ActionCommand.STORE_VERIFICATION,)


def test_unknown_result_can_resolve_failed_only_with_non_execution_proof():
    with pytest.raises(InvariantViolationError):
        transition_resolve_as_failed(ActionStatus.UNKNOWN_RESULT, current_version=1, expected_version=1, result_not_executed_confirmed=False)


def test_verification_mismatch_is_terminal_mismatch():
    result = transition_store_verification(ActionStatus.EXECUTED, current_version=4, expected_version=4, verification_status=VerificationStatus.MISMATCH)
    assert result.current_status is ActionStatus.MISMATCH
    assert result.next_allowed_commands == ()


def test_retry_only_starts_from_failed_and_returns_modified():
    result = transition_prepare_write_retry(ActionStatus.FAILED, current_version=2, expected_version=2)
    assert result.current_status is ActionStatus.MODIFIED
