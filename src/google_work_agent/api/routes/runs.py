"""Run routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Request, Response, status

from google_work_agent.adapters.runtime import RuntimeOperation
from google_work_agent.api.dependencies import (
    calculate_server_request_hash,
    enforce_access,
    enforce_api_contract_version,
    enforce_runtime_operation,
    get_container,
)
from google_work_agent.api.errors import ApiError, http_status_for_result_code
from google_work_agent.api.schemas.runs import (
    CancelRunRequestV2,
    ConfirmationResponseV1,
    ResolveRecoveryRequestV1,
    ResumeRunRequestV2,
    RunCommandResponse,
    RunContextResponse,
    RunSnapshotResponse,
    StartRunRequest,
    StartRunResponseModel,
)
from google_work_agent.application.start_run import ResumeRunCommand, StartRunCommand
from google_work_agent.ports import EndpointPolicy, SelectedResourceRef

router = APIRouter(prefix="/api/v1")


@router.post("/runs", response_model=StartRunResponseModel, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    request: Request, payload: StartRunRequest, response: Response
) -> StartRunResponseModel:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    command_payload = payload.model_dump()
    command_payload["request_hash"] = calculate_server_request_hash(
        operation="StartRunRequestV1",
        payload={"request": command_payload},
    )
    selected_resources = tuple(
        SelectedResourceRef(**item) for item in command_payload.pop("selected_resources")
    )
    command_payload["selected_resource_ids"] = tuple(command_payload["selected_resource_ids"])
    result = container.start_run_service(
        StartRunCommand(**command_payload, selected_resources=selected_resources)
    )
    if result.applied and result.enqueued:
        try:
            container.local_run_coordinator.enqueue_start(
                run_id=result.run_id,
                request_id=request.state.request_id,
                command_id=payload.command_id,
            )
        except Exception as error:
            raise ApiError(
                error_code="SERVICE_BUSY",
                user_message="로컬 실행 대기열이 가득 찼습니다.",
                status_code=503,
                request_id=request.state.request_id,
                retryable=True,
                detail_code=type(error).__name__,
            ) from error
    status_code = http_status_for_result_code(result.result_code, default_success=202)
    if status_code != 202:
        response.status_code = status_code
    return StartRunResponseModel(**asdict(result))


@router.get("/runs/{run_id}", response_model=RunSnapshotResponse)
def get_run_snapshot(
    run_id: str, request: Request, x_api_contract_version: str | None = Header(default=None)
) -> RunSnapshotResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    snapshot = container.query_service.get_run_snapshot(run_id)
    if snapshot is None:
        raise ApiError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return RunSnapshotResponse(
        snapshot=asdict(snapshot), api_contract_version=container.api_contract_version
    )


@router.get("/runs/{run_id}/context", response_model=RunContextResponse)
def get_run_context(
    run_id: str, request: Request, x_api_contract_version: str | None = Header(default=None)
) -> RunContextResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    context = container.query_service.get_run_execution_context(run_id)
    return RunContextResponse(
        context=None if context is None else asdict(context),
        api_contract_version=container.api_contract_version,
    )


@router.post("/runs/{run_id}/cancel", response_model=RunCommandResponse)
def cancel_run(
    run_id: str, request: Request, payload: CancelRunRequestV2, response: Response
) -> RunCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    from google_work_agent.application.write_actions import RequestRunCancellationCommand

    result = container.cancel_run_service(
        RequestRunCancellationCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="CancelRunRequestV2",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            run_id=run_id,
            expected_run_version=payload.expected_run_version,
        )
    )
    if result.applied and result.run_status == "CANCEL_REQUESTED":
        container.local_run_coordinator.request_cancel(
            run_id=run_id,
            request_id=request.state.request_id,
            reason_code="user_requested",
        )
    status_code = http_status_for_result_code(result.result_code)
    response.status_code = status_code
    return RunCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        run_id=result.run_id,
        run_status=result.run_status,
        run_version=result.run_version,
        conflict_detail=result.conflict_detail,
        result_kind=result.result_kind,
    )


@router.post("/runs/{run_id}/resume", response_model=RunCommandResponse)
def resume_run(
    run_id: str, request: Request, payload: ResumeRunRequestV2, response: Response
) -> RunCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    result = container.resume_run_service(
        ResumeRunCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ResumeRunRequestV2",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            run_id=run_id,
            expected_run_version=payload.expected_version,
            resume_kind=payload.resume_kind,
            api_contract_version=payload.api_contract_version,
        )
    )
    if result.applied and result.should_enqueue:
        container.local_run_coordinator.enqueue_resume(
            run_id=run_id,
            request_id=request.state.request_id,
            command_id=payload.command_id,
            resume_kind=payload.resume_kind,
            resume_payload={},
        )
    status_code = http_status_for_result_code(result.result_code)
    response.status_code = status_code
    return RunCommandResponse(**asdict(result))


@router.post("/runs/{run_id}/confirm", response_model=RunCommandResponse)
def confirm_run(
    run_id: str,
    request: Request,
    payload: ConfirmationResponseV1,
    response: Response,
) -> RunCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    result = container.resume_run_service(
        ResumeRunCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ConfirmationResponseV1",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            run_id=run_id,
            expected_run_version=payload.expected_version,
            resume_kind="CONFIRMATION",
            api_contract_version=payload.api_contract_version,
        )
    )
    if result.applied and result.should_enqueue:
        container.local_run_coordinator.enqueue_resume(
            run_id=run_id,
            request_id=request.state.request_id,
            command_id=payload.command_id,
            resume_kind="CONFIRMATION",
            resume_payload={
                "schema_version": 1,
                "interrupt_id": payload.interrupt_id,
                "response_kind": payload.response_kind,
                "selected_option_ids": payload.selected_option_ids,
                "free_text": None if payload.free_text is None else payload.free_text.strip(),
            },
        )
    response.status_code = http_status_for_result_code(result.result_code)
    return RunCommandResponse(**asdict(result))


@router.post("/runs/{run_id}/resolve-recovery", response_model=RunCommandResponse)
def resolve_recovery(
    run_id: str,
    request: Request,
    payload: ResolveRecoveryRequestV1,
    response: Response,
) -> RunCommandResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RUN_COMMANDS)
    from google_work_agent.application.write_actions import (
        RecoveryResolutionKind,
        ResolveMismatchRecoveryCommand,
        ResolveMismatchRecoveryService,
    )

    service = container.resolve_recovery_service or ResolveMismatchRecoveryService(
        unit_of_work_factory=container.unit_of_work_factory,
        now_ms=container.clock.now_ms,
    )
    result = service(
        ResolveMismatchRecoveryCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ResolveRecoveryRequestV1",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            run_id=run_id,
            action_id=payload.action_id,
            expected_run_version=payload.expected_version,
            resolution_kind=RecoveryResolutionKind(payload.resolution_kind),
            corrective_plan_id=(
                container.id_generator.next_id()
                if payload.resolution_kind == "CREATE_CORRECTIVE_PLAN"
                else None
            ),
        )
    )
    response.status_code = (
        422
        if result.result_code == "STATE_CONFLICT"
        else http_status_for_result_code(result.result_code)
    )
    return RunCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        run_id=result.run_id,
        run_status=result.run_status,
        run_version=result.run_version,
        conflict_detail=result.conflict_detail,
        result_kind=result.result_kind,
    )
