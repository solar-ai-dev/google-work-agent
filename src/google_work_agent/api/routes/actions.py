"""Existing action command routes."""

from fastapi import APIRouter, Request, Response

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.errors import http_status_for_result_code
from google_work_agent.api.schemas.actions import (
    ActionCommandResponse,
    ApproveActionRequest,
    ModifyActionRequest,
    PrepareRetryRequest,
    RejectActionRequest,
)
from google_work_agent.application.start_run import (
    ModifyWriteActionCommand,
    RejectWriteActionCommand,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/actions")


@router.post("/{action_id}/approve", response_model=ActionCommandResponse)
def approve(
    action_id: str, request: Request, payload: ApproveActionRequest, response: Response
) -> ActionCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    from google_work_agent.application.write_actions import ApproveWriteActionCommand

    result = container.approve_action_service(
        ApproveWriteActionCommand(
            command_id=payload.command_id,
            request_hash=payload.request_hash,
            action_id=action_id,
            expected_version=payload.expected_version,
            approved_by_account_id=payload.approved_by_account_id,
            approved_by_display=payload.approved_by_display,
            source_snapshot=payload.source_snapshot,
            approval_id=payload.approval_id,
            idempotency_key=payload.idempotency_key,
            ttl_ms=payload.ttl_ms,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return ActionCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        action_id=result.action_id,
        action_status=result.action_status,
        action_version=result.action_version,
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


@router.post("/{action_id}/modify", response_model=ActionCommandResponse)
def modify(
    action_id: str, request: Request, payload: ModifyActionRequest, response: Response
) -> ActionCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    result = container.modify_action_service(
        ModifyWriteActionCommand(
            command_id=payload.command_id,
            request_hash=payload.request_hash,
            action_id=action_id,
            expected_version=payload.expected_version,
        )
    )
    response.status_code = http_status_for_result_code(str(result["result_code"]))
    return ActionCommandResponse(
        applied=bool(result["applied"]),
        result_code=str(result["result_code"]),
        action_id=str(result["action_id"]),
        action_status=str(result["action_status"]),
        action_version=int(result["action_version"]),
        next_allowed_commands=[str(item) for item in result["next_allowed_commands"]],
        conflict_detail=None
        if result["conflict_detail"] is None
        else str(result["conflict_detail"]),
    )


@router.post("/{action_id}/reject", response_model=ActionCommandResponse)
def reject(
    action_id: str, request: Request, payload: RejectActionRequest, response: Response
) -> ActionCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    result = container.reject_action_service(
        RejectWriteActionCommand(
            command_id=payload.command_id,
            request_hash=payload.request_hash,
            action_id=action_id,
            expected_version=payload.expected_version,
        )
    )
    response.status_code = http_status_for_result_code(str(result["result_code"]))
    return ActionCommandResponse(
        applied=bool(result["applied"]),
        result_code=str(result["result_code"]),
        action_id=str(result["action_id"]),
        action_status=str(result["action_status"]),
        action_version=int(result["action_version"]),
        next_allowed_commands=[str(item) for item in result["next_allowed_commands"]],
        conflict_detail=None
        if result["conflict_detail"] is None
        else str(result["conflict_detail"]),
    )


@router.post("/{action_id}/prepare-retry", response_model=ActionCommandResponse)
def prepare_retry(
    action_id: str, request: Request, payload: PrepareRetryRequest, response: Response
) -> ActionCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    from google_work_agent.application.write_actions import PrepareWriteRetryCommand

    result = container.prepare_retry_service(
        PrepareWriteRetryCommand(
            command_id=payload.command_id,
            request_hash=payload.request_hash,
            action_id=action_id,
            expected_action_version=payload.expected_action_version,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return ActionCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        action_id=result.action_id,
        action_status=result.action_status,
        action_version=result.action_version,
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )
