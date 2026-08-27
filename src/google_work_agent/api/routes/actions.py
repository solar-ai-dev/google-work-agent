"""Action command transport routes."""

from typing import Protocol

from fastapi import APIRouter, Request, Response

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.actions import ActionRouteDependency
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
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
    ApproveActionHandler,
)
from google_work_agent.application.use_cases.action.modify_action import (
    ModifyActionCommand,
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


class _VersionedPayload(Protocol):
    api_contract_version: str


class _ActionResult(Protocol):
    @property
    def applied(self) -> bool: ...

    @property
    def result_code(self) -> str: ...

    @property
    def action_id(self) -> str: ...

    @property
    def action_status(self) -> str: ...

    @property
    def action_version(self) -> int: ...

    @property
    def next_allowed_commands(self) -> tuple[str, ...]: ...

    @property
    def conflict_detail(self) -> str | None: ...


def _prepare(
    request: Request, *, payload: _VersionedPayload, dependencies: ActionRouteDependency
) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="APPROVALS")


def _response(result: _ActionResult) -> ActionCommandResponse:
    return ActionCommandResponse(
        applied=bool(result.applied),
        result_code=str(result.result_code),
        action_id=str(result.action_id),
        action_status=str(result.action_status),
        action_version=int(result.action_version),
        next_allowed_commands=list(result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


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
        id_generator=dependencies.id_generator,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
    )
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
    if dependencies.action_gateway is None:
        raise RuntimeError("modify action gateway is not configured")
    handler = ModifyActionHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        gateway=dependencies.action_gateway,
        id_generator=dependencies.id_generator,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
    )
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
