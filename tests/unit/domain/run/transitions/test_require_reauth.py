import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.require_reauth import transition_require_reauth


def test_require_reauth_applies_canonical_transition():
    assert (
        transition_require_reauth(
            RunStatusV1.ANALYZING,
            target_kind="AGENT_NODE",
            target_stage=None,
            binding_is_current=True,
            action_statuses=(),
            attempt_statuses=(),
            has_legacy_read_executing=False,
            delivery_uncertain=False,
            cancel_intent_active=False,
        )
        is RunStatusV1.REAUTH_REQUIRED
    )


def test_require_reauth_rejects_preflight_after_dispatch():
    with pytest.raises(RunTransitionRejected):
        transition_require_reauth(
            RunStatusV1.WAITING_APPROVAL,
            target_kind="MAIN_CONTROL",
            target_stage="PREFLIGHT",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTING,),
            attempt_statuses=(ExecutionAttemptStatusV1.EXECUTING,),
            has_legacy_read_executing=False,
            delivery_uncertain=True,
            cancel_intent_active=False,
        )


def test_require_reauth_allows_only_safe_legacy_read_resume():
    assert (
        transition_require_reauth(
            RunStatusV1.EXECUTING,
            target_kind="MAIN_CONTROL",
            target_stage="READ_EXECUTION",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTING,),
            attempt_statuses=(),
            has_legacy_read_executing=True,
            delivery_uncertain=False,
            cancel_intent_active=False,
        )
        is RunStatusV1.REAUTH_REQUIRED
    )
