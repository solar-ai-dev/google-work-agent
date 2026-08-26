from google_work_agent.domain.enums import ActionStatus, VerificationStatus
from google_work_agent.domain.verification.transitions.store_verification import (
    transition_store_verification,
)


def test_store_verification_mismatch_is_a_terminal_fact() -> None:
    result = transition_store_verification(
        ActionStatus.EXECUTED,
        current_version=4,
        expected_version=4,
        verification_status=VerificationStatus.MISMATCH,
    )

    assert result.current_status is ActionStatus.MISMATCH
    assert result.next_allowed_commands == ()
