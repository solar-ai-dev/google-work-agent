"""Run routes."""

from collections.abc import Iterator
from dataclasses import asdict
from json import dumps
from typing import Any, cast

from fastapi import APIRouter, Header, Request, Response, status
from fastapi.responses import StreamingResponse

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.request_hash import calculate_server_request_hash
from google_work_agent.api.dependencies.runs import RunEventRouteDependency, RunRouteDependency
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.errors.result_code_http_mapping import http_status_for_result_code
from google_work_agent.api.schemas.runs.adjust_context import (
    AdjustContextRequestV1,
    AdjustContextResponseV1,
)
from google_work_agent.api.schemas.runs.cancel_run import CancelRunRequestV2, RunCommandResponse
from google_work_agent.api.schemas.runs.confirm_run import ConfirmationResponseV1
from google_work_agent.api.schemas.runs.get_run_context import (
    ExecutionContextResponse,
    RunContextResponse,
)
from google_work_agent.api.schemas.runs.get_run_snapshot import RunSnapshotResponseV1
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2
from google_work_agent.api.schemas.runs.start_run import StartRunRequest, StartRunResponseV1
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.resource.issue_selection_handle import (
    ResourceSelectionHandlePayloadV1,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandleQuery,
    SelectionHandleValidationError,
)
from google_work_agent.application.use_cases.run.adjust_context import (
    AdjustContextCommandV1,
    AdjustContextHandler,
)
from google_work_agent.application.use_cases.run.confirm_run import (
    ConfirmRunCommand,
)
from google_work_agent.application.use_cases.run.get_execution_context import (
    GetExecutionContextQuery,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import GetRunSnapshotQuery
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
)
from google_work_agent.application.use_cases.run.resume_after_reauth import (
    ResumeAfterReauthCommand,
)
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    ResumeSafeCheckpointCommand,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand
from google_work_agent.application.use_cases.sse_event.list_run_events import ListRunEventsQuery
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.post("/runs", response_model=StartRunResponseV1, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    request: Request, payload: StartRunRequest, response: Response, dependencies: RunRouteDependency
) -> StartRunResponseV1:
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
    if dependencies.start_run_handler is None:
        raise RuntimeError("start-run handler is not configured")
    result = dependencies.start_run_handler(
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
    return StartRunResponseV1(
        run_id=result.run_id,
        conversation_id=result.conversation_id,
        langgraph_thread_id=result.workflow_key,
        status=result.run_status,
        version=result.run_version,
        event_stream_url=f"/api/v1/runs/{result.run_id}/events",
    )


def _resolve_start_run_selections(
    *,
    request: Request,
    dependencies: RunRouteDependency,
    selection_handles: tuple[str, ...],
) -> tuple[ResourceSelectionHandlePayloadV1, ...]:
    if not selection_handles:
        return ()
    session_token = request.cookies.get(local_session_cookie_name(dependencies.service_instance_id))
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


@router.get("/runs/{run_id}", response_model=RunSnapshotResponseV1)
def get_run_snapshot(
    run_id: str,
    request: Request,
    dependencies: RunRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RunSnapshotResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    if dependencies.get_run_snapshot_handler is None:
        raise RuntimeError("run-snapshot handler is not configured")
    snapshot = dependencies.get_run_snapshot_handler(GetRunSnapshotQuery(run_id=run_id))
    if snapshot is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    return RunSnapshotResponseV1.model_validate(asdict(snapshot))


@router.get("/runs/{run_id}/events")
def stream_events(
    run_id: str,
    request: Request,
    dependencies: RunEventRouteDependency,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    x_api_contract_version: str | None = Header(default=None),
) -> StreamingResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    query = ListRunEventsQuery(run_id=run_id, last_event_id=last_event_id)
    if dependencies.list_run_events_handler is None:
        raise RuntimeError("run-event handler is not configured")
    replay = dependencies.list_run_events_handler(query)
    if not replay.run_exists:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    if replay.cursor_status == "CURSOR_EXPIRED":
        return StreamingResponse(
            iter((_format_sse("", "snapshot_required", {"run_id": run_id}),)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    if dependencies.event_buffer is None:
        raise RuntimeError("run-event transport is not configured")
    transport = cast(Any, dependencies.event_buffer)
    subscription = transport.subscribe(run_id)
    catchup = dependencies.list_run_events_handler(query)

    def _stream() -> Iterator[str]:
        emitted_ids: set[str] = set()
        try:
            for event in catchup.events:
                emitted_ids.add(event.event_id)
                yield _format_sse(event.event_id, event.event_type, event.payload)
            while True:
                maybe_event = subscription.poll(0.1)
                if maybe_event is None:
                    yield ": keepalive\n\n"
                    continue
                if maybe_event.event_id in emitted_ids:
                    continue
                emitted_ids.add(maybe_event.event_id)
                yield _format_sse(maybe_event.event_id, maybe_event.event_type, maybe_event.payload)
        finally:
            transport.close_subscription(subscription)

    return StreamingResponse(
        _stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


def _format_sse(event_id: str, event_type: str, payload: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {dumps(payload, sort_keys=True)}\n\n"


@router.post(
    "/runs/{run_id}/context-adjustments",
    response_model=AdjustContextResponseV1,
)
def adjust_context(
    run_id: str,
    request: Request,
    payload: AdjustContextRequestV1,
    response: Response,
    dependencies: RunRouteDependency,
) -> AdjustContextResponseV1:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_runtime_operation(request, operation="RUN_COMMANDS")
    handler = dependencies.adjust_context_handler
    if not isinstance(handler, AdjustContextHandler):
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="Context adjustment is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="CONTEXT_ADJUSTMENT_UNAVAILABLE",
        )
    result = handler(
        AdjustContextCommandV1(
            schema_version=payload.schema_version,
            command_id=payload.command_id,
            run_id=run_id,
            expected_version=payload.expected_version,
            expected_retrieval_revision=payload.expected_retrieval_revision,
            adjustment_kind=payload.adjustment_kind,
            segment_ids=None if payload.segment_ids is None else tuple(payload.segment_ids),
            requested_information=payload.requested_information,
        )
    )
    response.status_code = status.HTTP_200_OK if result.accepted else status.HTTP_409_CONFLICT
    return AdjustContextResponseV1(**asdict(result))


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
    if dependencies.get_execution_context_handler is None:
        raise RuntimeError("execution-context handler is not configured")
    context = dependencies.get_execution_context_handler(GetExecutionContextQuery(run_id=run_id))
    return RunContextResponse(
        context=None if context is None else ExecutionContextResponse(**asdict(context)),
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
    if dependencies.request_cancel_handler is None:
        raise RuntimeError("request-cancel handler is not configured")
    result = dependencies.request_cancel_handler(
        RequestCancelCommand(
            run_id=run_id,
            expected_version=payload.expected_version,
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
    if payload.resume_kind == "SAFE_CHECKPOINT_RESUME":
        if dependencies.resume_safe_checkpoint_handler is None:
            raise RuntimeError("safe-checkpoint resume handler is not configured")
        safe = dependencies.resume_safe_checkpoint_handler(
            ResumeSafeCheckpointCommand(
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ResumeRunRequestV2",
                    payload={"run_id": run_id, **payload.model_dump()},
                ),
                run_id=run_id,
                expected_run_version=payload.expected_version,
            )
        )
        response.status_code = http_status_for_result_code(safe.result_code)
        return RunCommandResponse(
            applied=safe.applied,
            result_code=safe.result_code,
            run_id=safe.run_id,
            run_status=safe.run_status,
            run_version=safe.run_version,
            should_enqueue=safe.handoff_id is not None,
            conflict_detail=safe.conflict_detail,
        )
    if payload.resume_kind == "RECOVERY_RECHECK":
        if dependencies.resolve_recovery_handler is None:
            raise RuntimeError("resolve-recovery handler is not configured")
        recovery = dependencies.resolve_recovery_handler.resolve_current(
            run_id=run_id,
            expected_version=payload.expected_version,
            command_id=payload.command_id,
            request_hash=calculate_server_request_hash(
                operation="ResumeRunRequestV2",
                payload={"run_id": run_id, **payload.model_dump()},
            ),
            resolution=RecoveryResolution.RECHECK,
        )
        response.status_code = http_status_for_result_code(recovery.result_code)
        return RunCommandResponse(
            applied=recovery.applied,
            result_code=recovery.result_code,
            run_id=run_id,
            run_status=recovery.current_status,
            run_version=recovery.current_version,
            should_enqueue=False,
            conflict_detail=recovery.conflict_detail,
        )
    if dependencies.resume_after_reauth_handler is None:
        raise RuntimeError("reauth resume handler is not configured")
    result = dependencies.resume_after_reauth_handler(
        ResumeAfterReauthCommand(
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
    if dependencies.confirm_run_handler is None:
        raise RuntimeError("confirm-run handler is not configured")
    result = dependencies.confirm_run_handler(
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
    if dependencies.resolve_recovery_handler is None:
        raise RuntimeError("resolve-recovery handler is not configured")
    result = dependencies.resolve_recovery_handler.resolve_current(
        command_id=payload.command_id,
        request_hash=calculate_server_request_hash(
            operation="ResolveRecoveryRequestV1",
            payload={"run_id": run_id, **payload.model_dump()},
        ),
        run_id=run_id,
        expected_version=payload.expected_version,
        resolution=RecoveryResolution(payload.resolution_kind),
        requested_target_kind=payload.target.target_kind,
        requested_target_action_id=getattr(payload.target, "action_id", None),
    )
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
