"""Settings, backup, restore, and shutdown routes."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header, Request

from google_work_agent.adapters.runtime import RuntimeOperation, SettingsPatch
from google_work_agent.adapters.runtime.settings import WorkHours
from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    enforce_runtime_operation,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.settings import (
    BackupListResponse,
    BackupResponse,
    PatchSettingsRequest,
    RestorePlanRequest,
    RestorePlanResponse,
    SettingsResponse,
    ShutdownResponse,
)
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.get_settings_service
    if service is None:
        raise _service_unavailable(request, "SETTINGS_UNAVAILABLE")
    settings = service()
    return SettingsResponse(
        settings=asdict(settings),
        api_contract_version=container.api_contract_version,
    )


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(
    payload: PatchSettingsRequest,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SETTINGS)
    service = container.patch_settings_service
    if service is None:
        raise _service_unavailable(request, "SETTINGS_UNAVAILABLE")
    try:
        result = service(
            SettingsPatch(
                command_id=payload.command_id,
                requested_runtime_mode=payload.requested_runtime_mode,
                default_calendar_id=payload.default_calendar_id,
                default_tasklist_id=payload.default_tasklist_id,
                timezone=payload.timezone,
                work_hours=(
                    None
                    if payload.work_hours is None
                    else WorkHours(
                        days=tuple(payload.work_hours.days),
                        start=payload.work_hours.start,
                        end=payload.work_hours.end,
                    )
                ),
                approval_ttl_minutes=payload.approval_ttl_minutes,
                run_retention_days=payload.run_retention_days,
                external_llm_consent=payload.external_llm_consent,
                ollama_endpoint=payload.ollama_endpoint,
                approved_model_id=payload.approved_model_id,
                log_level=payload.log_level,
            )
        )
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="SETTINGS_VALIDATION_FAILED",
        ) from error
    return SettingsResponse(
        settings=asdict(result),
        api_contract_version=container.api_contract_version,
    )


@router.get("/backups", response_model=BackupListResponse)
def list_backups(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupListResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.BACKUP)
    service = container.list_backups_service
    if service is None:
        raise _service_unavailable(request, "BACKUP_UNAVAILABLE")
    return BackupListResponse(
        items=list(service()),
        api_contract_version=container.api_contract_version,
    )


@router.post("/backups", response_model=BackupResponse)
def create_backup(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.BACKUP)
    service = container.create_backup_service
    if service is None:
        raise _service_unavailable(request, "BACKUP_UNAVAILABLE")
    try:
        result = service()
    except ValueError as error:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message=str(error),
            status_code=409,
            request_id=request.state.request_id,
            detail_code="BACKUP_BLOCKED",
        ) from error
    return BackupResponse(
        backup={
            **asdict(result.backup),
            "database_path": str(result.database_path),
            "manifest_path": str(result.manifest_path),
        },
        api_contract_version=container.api_contract_version,
    )


@router.post("/restore", response_model=RestorePlanResponse)
def create_restore_plan(
    payload: RestorePlanRequest,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> RestorePlanResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.RESTORE)
    service = container.create_restore_plan_service
    if service is None:
        raise _service_unavailable(request, "RESTORE_UNAVAILABLE")
    try:
        plan = service(payload.backup_id)
    except ValueError as error:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="RESTORE_PLAN_INVALID",
        ) from error
    return RestorePlanResponse(
        plan={
            "backup": asdict(plan.backup),
            "backup_path": str(plan.backup_path),
            "current_db_backup_required": plan.current_db_backup_required,
            "downgrade_blocked": plan.downgrade_blocked,
        },
        api_contract_version=container.api_contract_version,
    )


@router.post("/control/shutdown", response_model=ShutdownResponse)
def shutdown(
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> ShutdownResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    enforce_runtime_operation(request, operation=RuntimeOperation.SHUTDOWN)
    service = container.request_shutdown_service
    if service is None:
        raise _service_unavailable(request, "SHUTDOWN_UNAVAILABLE")
    report = service()
    return ShutdownResponse(
        report=asdict(report),
        api_contract_version=container.api_contract_version,
    )


def _service_unavailable(request: Request, detail_code: str) -> ApiError:
    return ApiError(
        error_code="SERVICE_BUSY",
        user_message="서비스가 아직 준비되지 않았습니다.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )
