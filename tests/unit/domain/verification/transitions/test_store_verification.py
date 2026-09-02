import pytest

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.domain.verification.transitions.store_verification import (
    transition_store_verification,
)


def test_store_verification__mismatch_is__a_terminal_fact() -> None:
    result = transition_store_verification(
        ActionStatusV1.EXECUTED,
        current_version=4,
        expected_version=4,
        verification_status=VerificationStatus.MISMATCH,
    )

    assert result.current_status is ActionStatusV1.MISMATCH
    assert result.next_allowed_commands == ()


def test_store_verification__verified_is__a_terminal_fact() -> None:
    result = transition_store_verification(
        ActionStatusV1.EXECUTED,
        current_version=4,
        expected_version=4,
        verification_status=VerificationStatus.VERIFIED,
    )

    assert result.current_status is ActionStatusV1.VERIFIED


@pytest.mark.parametrize("observation", ["NOT_FOUND", "ERROR"])
def test_observation_failure__cannot_be_coerced__to_durable_mismatch(
    observation: str,
) -> None:
    with pytest.raises(ValueError, match="durable verification status"):
        transition_store_verification(
            ActionStatusV1.EXECUTED,
            current_version=4,
            expected_version=4,
            verification_status=observation,  # type: ignore[arg-type]
        )
