"""Settings, backup, restore, and shutdown routes."""

from __future__ import annotations

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies import SettingsRouteDependency, enforce_access, enforce_runtime_operation, enforce_supported_api_contract_version
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.settings import BackupListResponse, BackupResponse, PatchSettingsRequest, RestorePlanRequest, RestorePlanResponse, SettingsResponse, ShutdownResponse
from google_work_agent.application.use_cases.backup.create_backup import CreateBackupCommand, CreateBackupHandler
from google_work_agent.application.use_cases.backup.create_restore_plan import CreateRestorePlanCommand, CreateRestorePlanHandler
from google_work_agent.application.use_cases.backup.list_backups import ListBackupsHandler, ListBackupsQuery
from google_work_agent.application.use_cases.runtime.request_shutdown import RequestShutdownCommand, RequestShutdownHandler
from google_work_agent.application.use_cases.settings.get_settings import GetSettingsHandler, GetSettingsQuery
from google_work_agent.application.use_cases.settings.update_settings import UpdateSettingsCommand, UpdateSettingsHandler, UpdateWorkHours
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1")


def _contract(request: Request, dependencies: SettingsRouteDependency, version: str | None, operation: str) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(supported_version=dependencies.api_contract_version, request_id=request.state.request_id, request_version=version)
    enforce_runtime_operation(request, operation=operation)


@router.get("/settings", response_model=SettingsResponse)
def get_settings(request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    try:
        result = GetSettingsHandler(service_factory=dependencies.get_settings_service).handle(GetSettingsQuery())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return SettingsResponse(settings=result.settings, api_contract_version=dependencies.api_contract_version)


@router.patch("/settings", response_model=SettingsResponse)
def patch_settings(payload: PatchSettingsRequest, request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    try:
        result = UpdateSettingsHandler(service_factory=dependencies.patch_settings_service).handle(UpdateSettingsCommand(command_id=payload.command_id, requested_runtime_mode=payload.requested_runtime_mode, default_calendar_id=payload.default_calendar_id, default_tasklist_id=payload.default_tasklist_id, timezone=payload.timezone, work_hours=None if payload.work_hours is None else UpdateWorkHours(days=tuple(payload.work_hours.days), start=payload.work_hours.start, end=payload.work_hours.end), approval_ttl_minutes=payload.approval_ttl_minutes, run_retention_days=payload.run_retention_days, external_llm_consent=payload.external_llm_consent, ollama_endpoint=payload.ollama_endpoint, approved_model_id=payload.approved_model_id, log_level=payload.log_level))
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiError(error_code="INVALID_ARGUMENT", user_message=str(error), status_code=422, request_id=request.state.request_id, detail_code="SETTINGS_VALIDATION_FAILED") from error
    return SettingsResponse(settings=result.settings, api_contract_version=dependencies.api_contract_version)


@router.get("/backups", response_model=BackupListResponse)
def list_backups(request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> BackupListResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    try:
        result = ListBackupsHandler(service_factory=dependencies.list_backups_service).handle(ListBackupsQuery())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return BackupListResponse(items=list(result.items), api_contract_version=dependencies.api_contract_version)


@router.post("/backups", response_model=BackupResponse)
def create_backup(request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> BackupResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    try:
        result = CreateBackupHandler(service_factory=dependencies.create_backup_service).handle(CreateBackupCommand())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiError(error_code="SERVICE_BUSY", user_message=str(error), status_code=409, request_id=request.state.request_id, detail_code="BACKUP_BLOCKED") from error
    return BackupResponse(backup=result.backup, api_contract_version=dependencies.api_contract_version)


@router.post("/restore", response_model=RestorePlanResponse)
def create_restore_plan(payload: RestorePlanRequest, request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> RestorePlanResponse:
    _contract(request, dependencies, x_api_contract_version, "RESTORE")
    try:
        result = CreateRestorePlanHandler(service_factory=dependencies.create_restore_plan_service).handle(CreateRestorePlanCommand(backup_id=payload.backup_id))
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiError(error_code="INVALID_ARGUMENT", user_message=str(error), status_code=422, request_id=request.state.request_id, detail_code="RESTORE_PLAN_INVALID") from error
    return RestorePlanResponse(plan=result.plan, api_contract_version=dependencies.api_contract_version)


@router.post("/control/shutdown", response_model=ShutdownResponse)
def shutdown(request: Request, dependencies: SettingsRouteDependency, x_api_contract_version: str | None = Header(default=None)) -> ShutdownResponse:
    _contract(request, dependencies, x_api_contract_version, "SHUTDOWN")
    try:
        result = RequestShutdownHandler(service_factory=dependencies.request_shutdown_service).handle(RequestShutdownCommand())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return ShutdownResponse(report=result.report, api_contract_version=dependencies.api_contract_version)


def _service_unavailable(request: Request, detail_code: str) -> ApiError:
    return ApiError(error_code="SERVICE_BUSY", user_message="서비스가 아직 준비되지 않았습니다.", status_code=503, request_id=request.state.request_id, detail_code=detail_code)
