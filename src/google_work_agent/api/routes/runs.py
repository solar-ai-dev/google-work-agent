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
from google_work_agent.api.schemas.runs.adjust_context import (
    AdjustContextRequestV1,
    AdjustContextResponseV1,
)
from google_work_agent.api.schemas.runs.cancel_run import CancelRunRequestV2, RunCommandResponse
from google_work_agent.api.schemas.runs.confirm_run import ConfirmationResponseV1
from google_work_agent.api.schemas.runs.get_run_context import RunContextResponse
from google_work_agent.api.schemas.runs.get_run_snapshot import RunSnapshotResponseV1
from google_work_agent.api.schemas.runs.recovery import RecoveryUiProjectionV1
from google_work_agent.api.schemas.runs.resolve_recovery import ResolveRecoveryRequestV1
from google_work_agent.api.schemas.runs.resume_run import ResumeRunRequestV2
from google_work_agent.api.schemas.runs.start_run import StartRunRequest, StartRunResponseModel
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.api.security.sessions import calculate_session_digest
from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
)
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryHandler,
    materialize_current_resolve_recovery_command,
)
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
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
)
from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ProjectExternalLlmTransferScopeHandler,
)
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
    RequestCancelHandler,
)
from google_work_agent.application.use_cases.run.resume_after_reauth import (
    ResumeAfterReauthCommand,
    ResumeAfterReauthHandler,
)
from google_work_agent.application.use_cases.run.resume_confirmation import (
    ResumeConfirmationHandler,
)
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    ResumeSafeCheckpointCommand,
    ResumeSafeCheckpointHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
)
from google_work_agent.domain.recovery.model import RecoveryResolution
from google_work_agent.ports.system.api_access_port import EndpointPolicy

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
        checkpoint_port=dependencies.checkpoint_port,
        now_ms=dependencies.clock.now_ms,
        id_factory=dependencies.id_generator.new_uuid,
        graph_profile=dependencies.graph_profile,
        graph_version=dependencies.graph_version,
        settings_provider=(
            None if dependencies.settings is None else dependencies.settings.get_settings
        ),
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
    snapshot = GetRunSnapshotHandler(
        unit_of_work_factory=dependencies.read_unit_of_work_factory,
        project_context_preview=(
            dependencies.project_context_preview_handler
            if isinstance(
                dependencies.project_context_preview_handler,
                ProjectContextPreviewHandler,
            )
            else None
        ),
        project_recovery_options=(
            dependencies.project_recovery_options_handler
            if isinstance(
                dependencies.project_recovery_options_handler,
                ProjectRecoveryOptionsHandler,
            )
            else None
        ),
        project_error_actions=(
            dependencies.project_error_actions_handler
            if isinstance(
                dependencies.project_error_actions_handler,
                ProjectErrorActionsHandler,
            )
            else None
        ),
        project_external_llm_transfer_scope=(
            dependencies.project_external_llm_transfer_scope_handler
            if isinstance(
                dependencies.project_external_llm_transfer_scope_handler,
                ProjectExternalLlmTransferScopeHandler,
            )
            else None
        ),
        resolve_pending_confirmation=dependencies.resolve_pending_confirmation,
    )(GetRunSnapshotQuery(run_id=run_id))
    if snapshot is None:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    canonical_projection = asdict(snapshot)
    recovery = canonical_projection["recovery"]
    canonical_projection["recovery"] = (
        None if recovery is None else RecoveryUiProjectionV1.model_validate(recovery).model_dump()
    )
    run_projection = canonical_projection.pop("run")
    projection = {
        **run_projection,
        **canonical_projection,
        "active_plan": canonical_projection.pop("current_plan"),
        "result_kind": canonical_projection.pop("terminal_result_kind"),
        "snapshot_version": canonical_projection.pop("projection_version"),
    }
    return RunSnapshotResponseV1(
        snapshot=projection, api_contract_version=dependencies.api_contract_version
    )


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
    context = GetExecutionContextHandler(
        unit_of_work_factory=dependencies.read_unit_of_work_factory,
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
        checkpoint_port=dependencies.checkpoint_port,
        now_ms=dependencies.clock.now_ms,
        id_generator=dependencies.id_generator,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
        continue_cancel_resolution=dependencies.continue_cancel_resolution,
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
    if payload.resume_kind == "SAFE_CHECKPOINT_RESUME":
        if dependencies.operational_command_replay is None:
            raise RuntimeError("operational command replay is not configured")
        safe = ResumeSafeCheckpointHandler(
            unit_of_work_factory=dependencies.unit_of_work_factory,
            checkpoint_port=dependencies.checkpoint_port,
            resume_target_registry=dependencies.resume_target_registry,
            schedule_run_execution=dependencies.schedule_run_execution,
            id_factory=dependencies.id_generator.new_uuid,
            operational_replay=dependencies.operational_command_replay,
            now_ms=dependencies.clock.now_ms,
        )(
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
        recovery = ResolveRecoveryHandler(
            unit_of_work_factory=dependencies.unit_of_work_factory,
            checkpoint_port=dependencies.checkpoint_port,
            now_ms=dependencies.clock.now_ms,
            next_id=dependencies.id_generator.new_uuid,
            resume_target_registry=dependencies.resume_target_registry,
            schedule_run_execution=dependencies.schedule_run_execution,
        )(
            materialize_current_resolve_recovery_command(
                dependencies.unit_of_work_factory,
                run_id=run_id,
                expected_version=payload.expected_version,
                command_id=payload.command_id,
                request_hash=calculate_server_request_hash(
                    operation="ResumeRunRequestV2",
                    payload={"run_id": run_id, **payload.model_dump()},
                ),
                resolution=RecoveryResolution.RECHECK,
            )
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
    handler = ResumeAfterReauthHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        checkpoint_port=dependencies.checkpoint_port,
        now_ms=dependencies.clock.now_ms,
        resolve_resume_authority=dependencies.resolve_resume_authority,
        id_generator=dependencies.id_generator,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
    )
    result = handler(
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
    resume_handler = ResumeConfirmationHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        checkpoint_port=dependencies.checkpoint_port,
        now_ms=dependencies.clock.now_ms,
        id_factory=dependencies.id_generator.new_uuid,
        resume_target_registry=dependencies.resume_target_registry,
    )
    handler = ConfirmRunHandler(
        resolve_pending_confirmation=dependencies.resolve_pending_confirmation,
        resume_confirmation=resume_handler,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
        id_factory=dependencies.id_generator.new_uuid,
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
        checkpoint_port=dependencies.checkpoint_port,
        now_ms=dependencies.clock.now_ms,
        next_id=dependencies.id_generator.new_uuid,
        resume_target_registry=dependencies.resume_target_registry,
        schedule_run_execution=dependencies.schedule_run_execution,
    )
    result = handler(
        materialize_current_resolve_recovery_command(
            dependencies.unit_of_work_factory,
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
        ),
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
