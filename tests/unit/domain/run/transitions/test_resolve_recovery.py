import pytest
from google_work_agent.domain.enums import RecoveryResolution,RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.resolve_recovery import transition_resolve_recovery

def test_resolve_recovery_enforces_cancel_intent_rules():
    assert transition_resolve_recovery(RunStatus.RECOVERY_REQUIRED,resolution=RecoveryResolution.RECHECK) is RunStatus.VERIFYING
    with pytest.raises(RunTransitionRejected):transition_resolve_recovery(RunStatus.RECOVERY_REQUIRED,resolution=RecoveryResolution.ACCEPT_PARTIAL,cancel_intent_active=True)
    assert transition_resolve_recovery(RunStatus.RECOVERY_REQUIRED,resolution=RecoveryResolution.CANCEL,cancel_intent_active=True,terminal_snapshot=True) is RunStatus.CANCELLED
