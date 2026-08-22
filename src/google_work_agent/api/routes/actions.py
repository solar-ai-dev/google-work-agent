"""Action command transport routes."""

from fastapi import APIRouter, Request, Response

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.actions import ActionRouteDependency
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.errors.result_code_http_mapping import http_status_for_result_code
from google_work_agent.api.schemas.actions.approve_action import (
    ActionCommandResponse,
    ApproveActionRequestV2,
)
from google_work_agent.api.schemas.actions.modify_action import ModifyActionRequestV2
from google_work_agent.api.schemas.actions.prepare_retry_action import PrepareRetryRequestV2
from google_work_agent.api.schemas.actions.reject_action import RejectActionRequestV2
from google_work_agent.application.use_cases.action.approve_action import (
    ApproveActionCommand,
    ApproveActionFollowupQueueBusyError,
    ApproveActionHandler,
)
from google_work_agent.application.use_cases.action.modify_action import (
    ModifyActionCommand,
    ModifyActionFollowupQueueBusyError,
    ModifyActionHandler,
)
from google_work_agent.application.use_cases.action.prepare_write_retry import (
    PrepareWriteRetryCommand,
    PrepareWriteRetryHandler,
)
from google_work_agent.application.use_cases.action.reject_action import (
    RejectActionCommand,
    RejectActionHandler,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/actions")


def _prepare(request: Request, *, payload: object, dependencies: ActionRouteDependency) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")


def _response(result: object) -> ActionCommandResponse:
    return ActionCommandResponse(
        applied=bool(result.applied),
        result_code=str(result.result_code),
        action_id=str(result.action_id),
        action_status=str(result.action_status),
        action_version=int(result.action_version),
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


def _modify_gateway(dependencies: ActionRouteDependency) -> object:
    """Temporary wiring bridge until shared API composition exposes the gateway directly."""
    legacy_surface = dependencies.modify_action_service()
    validator = getattr(legacy_surface, "_task_duplicates", None)
    gateway = getattr(validator, "_gateway", None)
    if gateway is None:
        raise RuntimeError("modify action gateway is not configured")
    return gateway


@router.post("/{action_id}/approve", response_model=ActionCommandResponse)
def approve(
    action_id: str,
    request: Request,
    payload: ApproveActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    _prepare(request, payload=payload, dependencies=dependencies)
    request_payload = payload.model_dump()
    request_payload.pop("ttl_ms", None)
    settings_service = dependencies.get_settings_service()
    if settings_service is None:
        raise RuntimeError("get_settings_service is not configured")
    handler = ApproveActionHandler(
        get_approval_ttl_minutes=lambda: settings_service().approval_ttl_minutes,
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        local_run_coordinator=dependencies.local_run_coordinator,
        id_generator=dependencies.id_generator,
    )
    try:
        result = handler(
            ApproveActionCommand(
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ApproveActionRequestV2",
                    payload={"action_id": action_id, **request_payload},
                ),
                request_id=request.state.request_id,
                action_id=action_id,
                expected_version=payload.expected_version,
                duplicate_acknowledged=payload.duplicate_acknowledged,
                calendar_conflict_acknowledged=payload.calendar_conflict_acknowledged,
            )
        )
    except ApproveActionFollowupQueueBusyError as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The approval was saved, but runtime execution is still queued.",
            status_code=503,
            request_id=request.state.request_id,
            retryable=True,
            detail_code=type(error).__name__,
            current_state=error.current_state,
        ) from error
    response.status_code = http_status_for_result_code(result.result_code)
    return _response(result)


@router.post("/{action_id}/modify", response_model=ActionCommandResponse)
def modify(
    action_id: str,
    request: Request,
    payload: ModifyActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    _prepare(request, payload=payload, dependencies=dependencies)
    handler = ModifyActionHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        gateway=_modify_gateway(dependencies),
        local_run_coordinator=dependencies.local_run_coordinator,
    )
    try:
        result = handler(
            ModifyActionCommand(
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ModifyActionRequestV2",
                    payload={"action_id": action_id, **payload.model_dump()},
                ),
                request_id=request.state.request_id,
                action_id=action_id,
                expected_version=payload.expected_version,
                arguments_patch=dict(payload.arguments_patch),
            )
        )
    except ModifyActionFollowupQueueBusyError as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The action was modified, but plan review is still queued.",
            status_code=503,
            request_id=request.state.request_id,
            retryable=True,
            detail_code=type(error).__name__,
            current_state=error.current_state,
        ) from error
    response.status_code = http_status_for_result_code(result.result_code)
    return _response(result)


@router.post("/{action_id}/reject", response_model=ActionCommandResponse)
def reject(
    action_id: str,
    request: Request,
    payload: RejectActionRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    _prepare(request, payload=payload, dependencies=dependencies)
    result = RejectActionHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        event_publisher=dependencies.event_publisher(),
    )(
        RejectActionCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="RejectActionRequestV2",
                payload={"action_id": action_id, **payload.model_dump()},
            ),
            action_id=action_id,
            expected_version=payload.expected_version,
            reason_code=payload.reason_code,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return _response(result)


@router.post("/{action_id}/prepare-retry", response_model=ActionCommandResponse)
def prepare_retry(
    action_id: str,
    request: Request,
    payload: PrepareRetryRequestV2,
    response: Response,
    dependencies: ActionRouteDependency,
) -> ActionCommandResponse:
    _prepare(request, payload=payload, dependencies=dependencies)
    result = PrepareWriteRetryHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
    )(
        PrepareWriteRetryCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="PrepareRetryRequestV2",
                payload={"action_id": action_id, **payload.model_dump()},
            ),
            action_id=action_id,
            expected_action_version=payload.expected_action_version,
        )
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return _response(result)
