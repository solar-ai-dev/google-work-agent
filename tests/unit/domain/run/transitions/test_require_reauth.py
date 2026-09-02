import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.require_reauth import transition_require_reauth


def test_require_reauth__applies_canonical__transition() -> None:
    assert (
        transition_require_reauth(
            RunStatusV1.ANALYZING,
            target_kind="AGENT_NODE",
            target_stage=None,
            binding_is_current=True,
            action_statuses=(),
            attempt_statuses=(),
            delivery_uncertain=False,
            cancel_intent_active=False,
        )
        is RunStatusV1.REAUTH_REQUIRED
    )


def test_require_reauth__rejects_preflight__after_dispatch() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_require_reauth(
            RunStatusV1.WAITING_APPROVAL,
            target_kind="MAIN_CONTROL",
            target_stage="PREFLIGHT",
            binding_is_current=True,
            action_statuses=(ActionStatusV1.EXECUTING,),
            attempt_statuses=(ExecutionAttemptStatusV1.EXECUTING,),
            delivery_uncertain=True,
            cancel_intent_active=False,
        )
