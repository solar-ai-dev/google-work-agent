"""Settings route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.backup.create_backup import CreateBackupHandler
from google_work_agent.application.use_cases.backup.list_backups import ListBackupsHandler
from google_work_agent.application.use_cases.backup.restore_backup import RestoreBackupHandler
from google_work_agent.application.use_cases.setting.get_settings import GetSettingsHandler
from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsHandler
from google_work_agent.application.use_cases.shutdown.request_shutdown import (
    RequestShutdownHandler,
)


@dataclass(frozen=True, slots=True)
class SettingsRouteDependencies:
    api_contract_version: str
    get_settings_handler: GetSettingsHandler | None
    update_settings_handler: UpdateSettingsHandler | None
    list_backups_handler: ListBackupsHandler | None
    create_backup_handler: CreateBackupHandler | None
    restore_backup_handler: RestoreBackupHandler | None
    request_shutdown_handler: RequestShutdownHandler | None


def get_settings_route_dependencies(request: Request) -> SettingsRouteDependencies:
    container = get_api_container(request)
    return SettingsRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_settings_handler=container.get_settings_handler,
        update_settings_handler=container.update_settings_handler,
        list_backups_handler=container.list_backups_handler,
        create_backup_handler=container.create_backup_handler,
        restore_backup_handler=container.restore_backup_handler,
        request_shutdown_handler=container.request_shutdown_handler,
    )


SettingsRouteDependency = Annotated[
    SettingsRouteDependencies,
    Depends(get_settings_route_dependencies),
]
