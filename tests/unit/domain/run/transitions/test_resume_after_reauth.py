import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_after_reauth import (
    transition_resume_after_reauth,
)


def test_resume_after_reauth_restores_persisted_safe_phase() -> None:
    assert (
        transition_resume_after_reauth(
            RunStatusV1.REAUTH_REQUIRED,
            resume_status=RunStatusV1.VERIFYING,
            target_kind="MAIN_CONTROL",
            target_stage="VERIFICATION",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTED,),
            attempt_statuses=(ExecutionAttemptStatusV1.SUCCEEDED,),
            has_legacy_read_executing=False,
            delivery_uncertain=True,
            cancel_intent_active=False,
        )
        is RunStatusV1.VERIFYING
    )


def test_resume_after_reauth_rejects_non_reauth_source() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_resume_after_reauth(
            RunStatusV1.PLANNING,
            resume_status=RunStatusV1.VERIFYING,
            target_kind="MAIN_CONTROL",
            target_stage="VERIFICATION",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTED,),
            attempt_statuses=(ExecutionAttemptStatusV1.SUCCEEDED,),
            has_legacy_read_executing=False,
            delivery_uncertain=True,
            cancel_intent_active=False,
        )


def test_resume_after_reauth_rejects_read_execution_after_cancel() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_resume_after_reauth(
            RunStatusV1.REAUTH_REQUIRED,
            resume_status=RunStatusV1.EXECUTING,
            target_kind="MAIN_CONTROL",
            target_stage="READ_EXECUTION",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTING,),
            attempt_statuses=(),
            has_legacy_read_executing=True,
            delivery_uncertain=False,
            cancel_intent_active=True,
        )
