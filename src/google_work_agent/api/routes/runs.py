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
from google_work_agent.api.schemas.runs.confirm_run import (
    ConfirmationResponseV1,
    PendingInterruptResponseV1,
)
from google_work_agent.api.schemas.runs.get_run import RunSnapshotResponse
from google_work_agent.api.schemas.runs.get_run_context import RunContextResponse
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2
from google_work_agent.api.schemas.runs.start_run import StartRunRequest, StartRunResponseModel
from google_work_agent.api.security.cookies import LOCAL_SESSION_COOKIE_NAME
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.coordinator import QueueBusyError
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommand,
    ResolveRecoveryHandler,
)
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    ResourceSelectionHandlePayloadV1,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
    SelectionHandleValidationError,
)
from google_work_agent.application.use_cases.run.confirm_run import (
    ConfirmRunCommand,
    ConfirmRunHandler,
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
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
)
from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunCommand,
    ResumeRunHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
)
from google_work_agent.domain.enums import RecoveryResolution
from google_work_agent.ports import EndpointPolicy

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
    selected_resource_handles = tuple(command_payload.pop("selected_resource_handles"))
    resolved_resource_selections = _resolve_start_run_selections(
        request=request,
        dependencies=dependencies,
        selection_handles=selected_resource_handles,
    )
    handler = StartRunHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        id_factory=dependencies.id_generator.next_id,
        graph_profile=dependencies.graph_profile,
        graph_version=dependencies.graph_version,
    )
    result = handler(
        StartRunCommand(
            **command_payload,
            resolved_resource_selections=resolved_resource_selections,
        )
    )
    if result.applied and result.enqueued:
        dependencies.schedule_run_execution(
            ScheduleRunExecutionCommand(handoff_id=result.handoff_id)
        )
    response.status_code = http_status_for_result_code(result.result_code, default_success=202)
    return StartRunResponseModel(**asdict(result))


def _resolve_start_run_selections(
    *,
    request: Request,
    dependencies: RunRouteDependency,
    selection_handles: tuple[str, ...],
) -> tuple[ResourceSelectionHandlePayloadV1, ...]:
    if not selection_handles:
        return ()
    session_token = request.cookies.get(LOCAL_SESSION_COOKIE_NAME)
    account_id = dependencies.current_account_id()
    if session_token is None or account_id is None:
        raise ApiRequestError(
            error_code="LOCAL_SESSION_INVALID",
            user_message="Resource selection requires an active account and local session.",
            status_code=401,
            request_id=request.state.request_id,
            detail_code="RESOURCE_SELECTION_BINDING_UNAVAILABLE",
        )
    session_digest = calculate_session_digest(session_token)
    try:
        return tuple(
            dependencies.resolve_selection_handle(
                ResolveSelectionHandleQuery(
                    selection_handle=handle,
                    session_digest=session_digest,
                    account_id=account_id,
                    expected_connector_id=dependencies.resource_connector_id,
                )
            )
            for handle in selection_handles
        )
    except SelectionHandleValidationError as error:
        raise ApiRequestError(
            error_code="INVALID_ARGUMENT",
            user_message="선택한 리소스의 인증 정보가 유효하지 않습니다.",
            status_code=422,
            request_id=request.state.request_id,
            detail_code="RESOURCE_SELECTION_HANDLE_INVALID",
        ) from error


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
    snapshot = GetRunSnapshotHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
    )(GetRunSnapshotQuery(run_id=run_id))
    if snapshot is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    projection = asdict(snapshot)
    pending = dependencies.resolve_pending_confirmation(run_id)
    if pending is not None:
        options = pending.get("options")
        projection["pending_interrupt"] = PendingInterruptResponseV1(
            interrupt_id=str(pending["interrupt_id"]),
            semantic_owner_id=pending["semantic_owner_id"],  # type: ignore[arg-type]
            question=str(pending["question"]),
            options=[] if not isinstance(options, list) else options,
            response_mode="FREE_TEXT" if not options else "OPTION",
        ).model_dump()
    else:
        projection["pending_interrupt"] = None
    return RunSnapshotResponse(
        snapshot=projection, api_contract_version=dependencies.api_contract_version
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
    context = GetExecutionContextHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
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
    resume_handler = ResumeConfirmationHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        id_factory=dependencies.id_generator.next_id,
        resume_target_registry=dependencies.resume_target_registry,  # type: ignore[arg-type]
    )
    handler = ConfirmRunHandler(
        resolve_pending_confirmation=dependencies.resolve_pending_confirmation,
        resume_confirmation=resume_handler,
        resume_target_registry=dependencies.resume_target_registry,  # type: ignore[arg-type]
        schedule_run_execution=dependencies.schedule_run_execution,
        id_factory=dependencies.id_generator.next_id,
    )
    result = handler(
        ConfirmRunCommand(
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ConfirmationResponseV1",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            run_id=run_id,
            expected_version=payload.expected_version,
            interrupt_id=payload.interrupt_id,
            response_kind=payload.response_kind,
            selected_option=payload.selected_option,
            free_text=None if payload.free_text is None else payload.free_text.strip(),
        ),
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
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        now_ms=dependencies.clock.now_ms,
        next_id=dependencies.id_generator.next_id,
    )
    try:
        result = handler(
            ResolveRecoveryCommand(
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ResolveRecoveryRequestV1",
                    payload={"run_id": run_id, **payload.model_dump()},
                ),
                run_id=run_id,
                expected_version=payload.expected_version,
                resolution=RecoveryResolution(payload.resolution_kind),
                irrecoverable_confirmed=payload.resolution_kind == "FAIL",
            ),
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
        run_id=run_id,
        run_status=result.current_status,
        run_version=result.current_version,
        conflict_detail=result.conflict_detail,
        result_kind=result.result_kind,
    )
