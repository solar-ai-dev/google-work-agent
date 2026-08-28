"""Settings, backup, restore, and shutdown routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, cast

from fastapi import APIRouter, Header, Request

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.runtime_operation import enforce_runtime_operation
from google_work_agent.api.dependencies.settings import SettingsRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.settings.create_backup import BackupResponse
from google_work_agent.api.schemas.settings.create_restore_plan import (
    RestorePlanRequest,
    RestorePlanResponse,
)
from google_work_agent.api.schemas.settings.get_settings import SettingsResponse
from google_work_agent.api.schemas.settings.list_backups import BackupListResponse
from google_work_agent.api.schemas.settings.request_shutdown import ShutdownResponse
from google_work_agent.api.schemas.settings.update_settings import PatchSettingsRequest
from google_work_agent.application.use_cases.backup.create_backup import (
    CreateBackupCommand,
    CreateBackupHandler,
)
from google_work_agent.application.use_cases.backup.list_backups import (
    ListBackupsHandler,
    ListBackupsQuery,
)
from google_work_agent.application.use_cases.backup.restore_backup import (
    RestoreBackupCommand,
    RestoreBackupHandler,
)
from google_work_agent.application.use_cases.setting.get_settings import (
    GetSettingsHandler,
    GetSettingsQuery,
)
from google_work_agent.application.use_cases.setting.update_settings import (
    UpdateSettingsCommand,
    UpdateSettingsHandler,
)
from google_work_agent.application.use_cases.shutdown.request_shutdown import (
    RequestShutdownCommand,
    RequestShutdownHandler,
)
from google_work_agent.ports import EndpointPolicy
from google_work_agent.ports.system.settings_port import SettingsPatchV1

router = APIRouter(prefix="/api/v1")


def _contract(
    request: Request, dependencies: SettingsRouteDependency, version: str | None, operation: str
) -> None:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=version,
    )
    enforce_runtime_operation(request, operation=operation)


@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    try:
        handler = dependencies.get_settings_handler()
        if not isinstance(handler, GetSettingsHandler):
            raise RuntimeError("SETTINGS_READ_UNAVAILABLE")
        result = handler(GetSettingsQuery())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return SettingsResponse(
        settings=asdict(result.settings), api_contract_version=dependencies.api_contract_version
    )


@router.put("/settings", response_model=SettingsResponse)
def patch_settings(
    payload: PatchSettingsRequest,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> SettingsResponse:
    _contract(request, dependencies, x_api_contract_version, "SETTINGS")
    try:
        handler = dependencies.update_settings_handler()
        if not isinstance(handler, UpdateSettingsHandler):
            raise RuntimeError("SETTINGS_UPDATE_UNAVAILABLE")
        result = handler(
            UpdateSettingsCommand(
                command_id=payload.command_id,
                settings_patch=SettingsPatchV1(
                    schema_version=1,
                    timezone=payload.timezone,
                    default_tasklist_id=payload.default_tasklist_id,
                    default_calendar_id=payload.default_calendar_id,
                    preferred_llm_mode=cast(
                        Literal["AUTO", "LOCAL_GPU", "API_LLM"] | None,
                        payload.requested_runtime_mode,
                    ),
                    external_llm_consent=payload.external_llm_consent,
                    retention_days=payload.run_retention_days,
                    working_day_start_local=(
                        None if payload.work_hours is None else payload.work_hours.start
                    ),
                    working_day_end_local=(
                        None if payload.work_hours is None else payload.work_hours.end
                    ),
                    include_weekends=(
                        None
                        if payload.work_hours is None
                        else any(day in {5, 6} for day in payload.work_hours.days)
                    ),
                ),
            )
        )
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiRequestError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="SETTINGS_VALIDATION_FAILED",
        ) from error
    return SettingsResponse(
        settings=asdict(result.settings), api_contract_version=dependencies.api_contract_version
    )


@router.get("/backups", response_model=BackupListResponse)
def list_backups(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupListResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    try:
        handler = dependencies.list_backups_handler()
        if not isinstance(handler, ListBackupsHandler):
            raise RuntimeError("BACKUP_LIST_UNAVAILABLE")
        result = handler(ListBackupsQuery())
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return BackupListResponse(
        items=[asdict(item) for item in result.backups],
        api_contract_version=dependencies.api_contract_version,
    )


@router.post("/backups", response_model=BackupResponse)
def create_backup(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> BackupResponse:
    _contract(request, dependencies, x_api_contract_version, "BACKUP")
    try:
        handler = dependencies.create_backup_handler()
        if not isinstance(handler, CreateBackupHandler):
            raise RuntimeError("BACKUP_CREATE_UNAVAILABLE")
        result = handler(CreateBackupCommand(command_id=request.state.request_id))
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message=str(error),
            status_code=409,
            request_id=request.state.request_id,
            detail_code="BACKUP_BLOCKED",
        ) from error
    return BackupResponse(
        backup=asdict(result.backup), api_contract_version=dependencies.api_contract_version
    )


@router.post("/restore", response_model=RestorePlanResponse)
def restore_backup(
    payload: RestorePlanRequest,
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> RestorePlanResponse:
    _contract(request, dependencies, x_api_contract_version, "RESTORE")
    try:
        handler = dependencies.restore_backup_handler()
        if not isinstance(handler, RestoreBackupHandler):
            raise RuntimeError("BACKUP_RESTORE_UNAVAILABLE")
        result = handler(
            RestoreBackupCommand(
                command_id=request.state.request_id,
                backup_ref=payload.backup_id,
            )
        )
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    except ValueError as error:
        raise ApiRequestError(
            error_code="INVALID_ARGUMENT",
            user_message=str(error),
            status_code=422,
            request_id=request.state.request_id,
            detail_code="RESTORE_PLAN_INVALID",
        ) from error
    return RestorePlanResponse(
        plan=asdict(result.restore), api_contract_version=dependencies.api_contract_version
    )


@router.post("/control/shutdown", response_model=ShutdownResponse)
def shutdown(
    request: Request,
    dependencies: SettingsRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> ShutdownResponse:
    _contract(request, dependencies, x_api_contract_version, "SHUTDOWN")
    try:
        handler = dependencies.request_shutdown_handler()
        if not isinstance(handler, RequestShutdownHandler):
            raise RuntimeError("SHUTDOWN_UNAVAILABLE")
        result = handler(RequestShutdownCommand(command_id=request.state.request_id))
    except RuntimeError as error:
        raise _service_unavailable(request, str(error)) from error
    return ShutdownResponse(
        report=asdict(result.shutdown), api_contract_version=dependencies.api_contract_version
    )


def _service_unavailable(request: Request, detail_code: str) -> ApiRequestError:
    return ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="서비스가 아직 준비되지 않았습니다.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )
