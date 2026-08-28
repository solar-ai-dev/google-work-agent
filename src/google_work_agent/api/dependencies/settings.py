"""Settings route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container


@dataclass(frozen=True, slots=True)
class SettingsRouteDependencies:
    api_contract_version: str
    get_settings_handler: Callable[[], object | None]
    update_settings_handler: Callable[[], object | None]
    list_backups_handler: Callable[[], object | None]
    create_backup_handler: Callable[[], object | None]
    restore_backup_handler: Callable[[], object | None]
    request_shutdown_handler: Callable[[], object | None]


def get_settings_route_dependencies(request: Request) -> SettingsRouteDependencies:
    container = get_api_container(request)
    return SettingsRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_settings_handler=lambda: container.get_settings_handler,
        update_settings_handler=lambda: container.update_settings_handler,
        list_backups_handler=lambda: container.list_backups_handler,
        create_backup_handler=lambda: container.create_backup_handler,
        restore_backup_handler=lambda: container.restore_backup_handler,
        request_shutdown_handler=lambda: container.request_shutdown_handler,
    )


SettingsRouteDependency = Annotated[
    SettingsRouteDependencies,
    Depends(get_settings_route_dependencies),
]
