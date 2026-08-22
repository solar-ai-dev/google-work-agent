"""Settings route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.settings import (
    CreateBackupService,
    CreateRestorePlanService,
    GetSettingsService,
    ListBackupsService,
    PatchSettingsService,
    RequestShutdownService,
)


@dataclass(frozen=True, slots=True)
class SettingsRouteDependencies:
    api_contract_version: str
    get_settings_service: Callable[[], GetSettingsService | None]
    patch_settings_service: Callable[[], PatchSettingsService | None]
    list_backups_service: Callable[[], ListBackupsService | None]
    create_backup_service: Callable[[], CreateBackupService | None]
    create_restore_plan_service: Callable[[], CreateRestorePlanService | None]
    request_shutdown_service: Callable[[], RequestShutdownService | None]


def get_settings_route_dependencies(request: Request) -> SettingsRouteDependencies:
    container = get_api_container(request)
    return SettingsRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_settings_service=lambda: container.get_settings_service,
        patch_settings_service=lambda: container.patch_settings_service,
        list_backups_service=lambda: container.list_backups_service,
        create_backup_service=lambda: container.create_backup_service,
        create_restore_plan_service=lambda: container.create_restore_plan_service,
        request_shutdown_service=lambda: container.request_shutdown_service,
    )


SettingsRouteDependency = Annotated[
    SettingsRouteDependencies,
    Depends(get_settings_route_dependencies),
]
