import pytest

from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.verification.model import VerificationStatus
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


def test_store_verification_verified_is_a_terminal_fact() -> None:
    result = transition_store_verification(
        ActionStatus.EXECUTED,
        current_version=4,
        expected_version=4,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert result.current_status is ActionStatus.VERIFIED


@pytest.mark.parametrize("observation", ["NOT_FOUND", "ERROR"])
def test_observation_failure_cannot_be_coerced_to_durable_mismatch(
    observation: str,
) -> None:
    with pytest.raises(ValueError, match="durable verification status"):
        transition_store_verification(
            ActionStatus.EXECUTED,
            current_version=4,
            expected_version=4,
            verification_status=observation,  # type: ignore[arg-type]
        )
