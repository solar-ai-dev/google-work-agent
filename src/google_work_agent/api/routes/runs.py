"""Run routes."""

from dataclasses import asdict

from fastapi import APIRouter, Header, Request, Response, status

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.dependencies.runs import RunRouteDependency
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.errors.result_code_http_mapping import http_status_for_result_code
from google_work_agent.api.schemas.runs.cancel_run import CancelRunRequestV2, RunCommandResponse
from google_work_agent.api.schemas.runs.confirm_run import ConfirmationResponseV1
from google_work_agent.api.schemas.runs.get_run import RunSnapshotResponse
from google_work_agent.api.schemas.runs.get_run_context import RunContextResponse
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2
from google_work_agent.api.schemas.runs.start_run import StartRunRequest, StartRunResponseModel
from google_work_agent.application.use_cases.recovery.resolve_mismatch_recovery import (
    MismatchRecoveryResolution,
    ResolveMismatchRecoveryCommand,
    ResolveMismatchRecoveryHandler,
)
from google_work_agent.application.use_cases.run.get_execution_context import (
    GetExecutionContextHandler,
    GetExecutionContextQuery,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
    GetRunSnapshotQuery,
)
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
    RequestCancelHandler,
)
from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunCommand,
    ResumeRunHandler,
)
from google_work_agent.application.use_cases.run.start_run import (
    QueueBusyError,
    StartRunCommand,
    StartRunHandler,
)
from google_work_agent.ports import EndpointPolicy, SelectedResourceRef

router = APIRouter(prefix="/api/v1")


@router.post("/runs", response_model=StartRunResponseModel, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    request: Request, payload: StartRunRequest, response: Response, dependencies: RunRouteDependency
) -> StartRunResponseModel:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    command_payload = payload.model_dump()
    command_payload["request_hash"] = calculate_server_request_hash(
        operation="StartRunRequestV1", payload={"request": command_payload}
    )
    selected_resources = tuple(
        SelectedResourceRef(**item) for item in command_payload.pop("selected_resources")
    )
    command_payload["selected_resource_ids"] = tuple(command_payload["selected_resource_ids"])
    handler = StartRunHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        reserve_queue_slot=dependencies.reserve_queue_slot,
        release_queue_slot=dependencies.release_queue_slot,
    )
    try:
        result = handler(StartRunCommand(**command_payload, selected_resources=selected_resources))
        if result.applied and result.enqueued:
            dependencies.local_run_coordinator.confirm_start(
                run_id=result.run_id,
                request_id=request.state.request_id,
                command_id=payload.command_id,
            )
    except QueueBusyError as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="로컬 실행 대기열이 가득 찼습니다.",
            status_code=503,
            request_id=request.state.request_id,
            retryable=True,
            detail_code=type(error).__name__,
        ) from error
    response.status_code = http_status_for_result_code(result.result_code, default_success=202)
    return StartRunResponseModel(**asdict(result))


@router.get("/runs/{run_id}", response_model=RunSnapshotResponse)
def get_run_snapshot(
    run_id: str,
    request: Request,
    dependencies: RunRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RunSnapshotResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    query_service = dependencies.query_service()
    snapshot = GetRunSnapshotHandler(
        database_path=query_service.database_path,
        connection_factory=query_service.connection_factory,
    )(GetRunSnapshotQuery(run_id=run_id))
    if snapshot is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return RunSnapshotResponse(
        snapshot=asdict(snapshot), api_contract_version=dependencies.api_contract_version
    )


@router.get("/runs/{run_id}/context", response_model=RunContextResponse)
def get_run_context(
    run_id: str,
    request: Request,
    dependencies: RunRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RunContextResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    query_service = dependencies.query_service()
    context = GetExecutionContextHandler(
        database_path=query_service.database_path,
        connection_factory=query_service.connection_factory,
    )(GetExecutionContextQuery(run_id=run_id))
    return RunContextResponse(
        context=None if context is None else asdict(context),
        api_contract_version=dependencies.api_contract_version,
    )


@router.post("/runs/{run_id}/cancel", response_model=RunCommandResponse)
def cancel_run(
    run_id: str,
    request: Request,
    payload: CancelRunRequestV2,
    response: Response,
    dependencies: RunRouteDependency,
) -> RunCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    result = RequestCancelHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        request_cancel_workflow=dependencies.local_run_coordinator.request_cancel,
    )(
        RequestCancelCommand(
            run_id=run_id,
            expected_version=payload.expected_run_version,
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="CancelRunRequestV2", payload={"run_id": run_id, **payload.model_dump()}
            ),
        ),
        request_id=request.state.request_id,
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return RunCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        run_id=run_id,
        run_status=result.current_status,
        run_version=result.current_version,
        conflict_detail=result.conflict_detail,
        result_kind=result.result_kind,
    )


@router.post("/runs/{run_id}/resume", response_model=RunCommandResponse)
def resume_run(
    run_id: str,
    request: Request,
    payload: ResumeRunRequestV2,
    response: Response,
    dependencies: RunRouteDependency,
) -> RunCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    handler = ResumeRunHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        enqueue_resume=dependencies.local_run_coordinator.enqueue_resume,
        resolve_resume_authority=dependencies.resolve_resume_authority,
    )
    result = handler(
        ResumeRunCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ResumeRunRequestV2", payload={"run_id": run_id, **payload.model_dump()}
            ),
            run_id=run_id,
            expected_run_version=payload.expected_version,
            resume_kind=payload.resume_kind,
            api_contract_version=payload.api_contract_version,
        ),
        request_id=request.state.request_id,
    )
    response.status_code = http_status_for_result_code(result.result_code)
    return RunCommandResponse(**asdict(result))


@router.post("/runs/{run_id}/confirm", response_model=RunCommandResponse)
def confirm_run(
    run_id: str,
    request: Request,
    payload: ConfirmationResponseV1,
    response: Response,
    dependencies: RunRouteDependency,
) -> RunCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    handler = ResumeRunHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        enqueue_resume=dependencies.local_run_coordinator.enqueue_resume,
        resolve_resume_authority=dependencies.resolve_resume_authority,
    )
    result = handler(
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
        ),
        request_id=request.state.request_id,
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
    dependencies: RunRouteDependency,
) -> RunCommandResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    handler = ResolveMismatchRecoveryHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        next_id=dependencies.id_generator.next_id,
        enqueue_resume=dependencies.local_run_coordinator.enqueue_resume,
    )
    try:
        result = handler(
            ResolveMismatchRecoveryCommand(
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ResolveRecoveryRequestV1",
                    payload={"run_id": run_id, **payload.model_dump()},
                ),
                run_id=run_id,
                action_id=payload.action_id,
                expected_version=payload.expected_version,
                resolution=MismatchRecoveryResolution(payload.resolution_kind),
            ),
            request_id=request.state.request_id,
        )
    except QueueBusyError as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="복구 계획을 이어서 처리할 수 없습니다.",
            status_code=503,
            request_id=request.state.request_id,
            retryable=True,
            detail_code=type(error).__name__,
        ) from error
    response.status_code = (
        422
        if result.result_code == "STATE_CONFLICT"
        else http_status_for_result_code(result.result_code)
    )
    return RunCommandResponse(
        applied=result.applied,
        result_code=result.result_code,
        run_id=result.run_id,
        run_status=result.current_status,
        run_version=result.current_version,
        conflict_detail=result.conflict_detail,
        result_kind=result.result_kind,
    )
