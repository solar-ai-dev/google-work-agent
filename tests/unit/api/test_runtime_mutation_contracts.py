import pytest
from pydantic import ValidationError
from tests.support.fakes import DeterministicUUID  # noqa: F401

from google_work_agent.api.dependencies import calculate_server_request_hash
from google_work_agent.api.schemas.actions import (
    ApproveActionRequestV2,
    ModifyActionRequestV2,
    PrepareRetryRequestV2,
    RejectActionRequestV2,
)
from google_work_agent.api.schemas.runs import (
    CancelRunRequestV2,
    ConfirmationResponseV1,
    ResolveRecoveryRequestV1,
    ResumeRunRequestV2,
)

VERSION = "1"


def test_server_request_hash_is_canonical_and_semantic() -> None:
    left = calculate_server_request_hash(
        operation="CancelRunRequestV2",
        payload={"command_id": "cmd-1", "expected_version": 3},
    )
    reordered = calculate_server_request_hash(
        operation="CancelRunRequestV2",
        payload={"expected_version": 3, "command_id": "cmd-1"},
    )
    changed = calculate_server_request_hash(
        operation="CancelRunRequestV2",
        payload={"command_id": "cmd-1", "expected_version": 4},
    )

    assert left == reordered
    assert left != changed
    assert len(left) == 64


@pytest.mark.parametrize(
    "schema,payload",
    [
        (
            ApproveActionRequestV2,
            {"command_id": "cmd", "expected_version": 1, "api_contract_version": VERSION},
        ),
        (
            ModifyActionRequestV2,
            {"command_id": "cmd", "expected_version": 1, "api_contract_version": VERSION},
        ),
        (
            RejectActionRequestV2,
            {"command_id": "cmd", "expected_version": 1, "api_contract_version": VERSION},
        ),
        (
            PrepareRetryRequestV2,
            {
                "command_id": "cmd",
                "expected_action_version": 1,
                "api_contract_version": VERSION,
            },
        ),
        (
            CancelRunRequestV2,
            {
                "command_id": "cmd",
                "expected_run_version": 1,
                "api_contract_version": VERSION,
            },
        ),
    ],
)
def test_versioned_mutation_schemas_accept_only_client_authority_fields(
    schema: type,
    payload: dict[str, object],
) -> None:
    assert schema.model_validate(payload)

    for forbidden in (
        "request_hash",
        "approval_id",
        "source_snapshot",
        "idempotency_key",
        "approved_by_account_id",
        "claim_token",
    ):
        with pytest.raises(ValidationError):
            schema.model_validate({**payload, forbidden: "browser-value"})


def test_confirmation_response_is_typed_and_mutually_exclusive() -> None:
    response = ConfirmationResponseV1.model_validate(
        {
            "command_id": "confirm-1",
            "expected_version": 2,
            "interrupt_id": "interrupt-1",
            "response_kind": "FREE_TEXT",
            "selected_option_ids": [],
            "free_text": "  Use the default task list.  ",
            "api_contract_version": VERSION,
        }
    )

    assert response.free_text == "  Use the default task list.  "
    with pytest.raises(ValidationError):
        ConfirmationResponseV1.model_validate(
            {
                **response.model_dump(),
                "selected_option_ids": ["default"],
            }
        )


def test_resume_rejects_arbitrary_payload_and_confirmation_kind() -> None:
    base = {
        "command_id": "resume-1",
        "expected_version": 2,
        "resume_kind": "RECOVERY_RECHECK",
        "api_contract_version": VERSION,
    }
    assert ResumeRunRequestV2.model_validate(base)

    with pytest.raises(ValidationError):
        ResumeRunRequestV2.model_validate({**base, "resume_payload": {"arbitrary": True}})
    with pytest.raises(ValidationError):
        ResumeRunRequestV2.model_validate({**base, "resume_kind": "CONFIRMATION"})


def test_recovery_schema_allows_only_two_canonical_choices() -> None:
    base = {
        "command_id": "recovery-1",
        "expected_version": 4,
        "action_id": "action-1",
        "resolution_kind": "ACCEPT_PARTIAL",
        "api_contract_version": VERSION,
    }
    assert ResolveRecoveryRequestV1.model_validate(base)

    with pytest.raises(ValidationError):
        ResolveRecoveryRequestV1.model_validate({**base, "resolution_kind": "RETRY_WRITE"})
