import pytest
from pydantic import BaseModel, ValidationError

from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.schemas.actions.approve_action import ApproveActionRequestV2
from google_work_agent.api.schemas.actions.modify_action import ModifyActionRequestV2
from google_work_agent.api.schemas.actions.prepare_retry import PrepareRetryRequestV2
from google_work_agent.api.schemas.actions.reject_action import RejectActionRequestV2
from google_work_agent.api.schemas.runs.cancel_run import CancelRunRequestV2
from google_work_agent.api.schemas.runs.confirm_run import ConfirmationResponseV1
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2

VERSION = "1"


def test_server_request__hash_is__canonical_and_semantic() -> None:
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
            {
                "command_id": "cmd",
                "expected_version": 1,
                "arguments_patch": {"title": "Updated title"},
                "api_contract_version": VERSION,
            },
        ),
        (
            RejectActionRequestV2,
            {"command_id": "cmd", "expected_version": 1, "api_contract_version": VERSION},
        ),
        (
            PrepareRetryRequestV2,
            {
                "command_id": "cmd",
                "expected_version": 1,
                "api_contract_version": VERSION,
            },
        ),
        (
            CancelRunRequestV2,
            {
                "command_id": "cmd",
                "expected_version": 1,
                "api_contract_version": VERSION,
            },
        ),
    ],
)
def test_versioned_mutation__schemas_accept_only__client_authority_fields(
    schema: type[BaseModel],
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
        "risk",
        "risk_json",
        "matched_resource_ids",
        "duplicate_decision",
    ):
        with pytest.raises(ValidationError):
            schema.model_validate({**payload, forbidden: "browser-value"})


def test_approve_accepts__only_duplicate_acknowledgement__not_duplicate_facts() -> None:
    payload = {
        "command_id": "approve-duplicate",
        "expected_version": 1,
        "duplicate_acknowledged": True,
        "api_contract_version": VERSION,
    }
    assert ApproveActionRequestV2.model_validate(payload).duplicate_acknowledged is True
    assert (
        ApproveActionRequestV2.model_validate(
            {**payload, "calendar_conflict_acknowledged": True}
        ).calendar_conflict_acknowledged
        is True
    )
    with pytest.raises(ValidationError):
        ApproveActionRequestV2.model_validate(
            {**payload, "matched_resource_ids": ["client-controlled"]}
        )


def test_confirmation_response__is_typed__and_mutually_exclusive() -> None:
    response = ConfirmationResponseV1.model_validate(
        {
            "command_id": "confirm-1",
            "expected_version": 2,
            "interrupt_id": "interrupt-1",
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "  Use the default task list.  ",
            "api_contract_version": VERSION,
        }
    )

    assert response.free_text == "  Use the default task list.  "
    with pytest.raises(ValidationError):
        ConfirmationResponseV1.model_validate(
            {
                **response.model_dump(),
                "selected_option": "default",
            }
        )


def test_resume_rejects__arbitrary_payload__and_confirmation_kind() -> None:
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


def test_recovery_schema_uses__shared_target_and__closed_resolution_vocabulary() -> None:
    base = {
        "command_id": "recovery-1",
        "expected_version": 4,
        "target": {"target_kind": "ACTION", "action_id": "action-1"},
        "resolution_kind": "ACCEPT_PARTIAL",
        "api_contract_version": VERSION,
    }
    assert ResolveRecoveryRequestV1.model_validate(base)
    for resolution_kind in ("RECHECK", "CREATE_CORRECTIVE_PLAN", "CANCEL", "FAIL"):
        assert ResolveRecoveryRequestV1.model_validate({**base, "resolution_kind": resolution_kind})
    assert ResolveRecoveryRequestV1.model_validate({**base, "target": {"target_kind": "RUN"}})

    with pytest.raises(ValidationError):
        ResolveRecoveryRequestV1.model_validate({**base, "resolution_kind": "RETRY_WRITE"})
    with pytest.raises(ValidationError):
        ResolveRecoveryRequestV1.model_validate({**base, "target": {"target_kind": "ACTION"}})
    with pytest.raises(ValidationError):
        ResolveRecoveryRequestV1.model_validate(
            {**base, "target": {"target_kind": "RUN", "action_id": "action-1"}}
        )
