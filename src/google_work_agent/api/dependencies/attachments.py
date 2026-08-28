"""Attachment route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container


@dataclass(frozen=True, slots=True)
class AttachmentRouteDependencies:
    api_contract_version: Callable[[], str]
    get_attachment_handler: Callable[[], object | None]
    create_staged_attachment_handler: Callable[[], object | None]


def get_attachment_route_dependencies(request: Request) -> AttachmentRouteDependencies:
    container = get_api_container(request)
    return AttachmentRouteDependencies(
        api_contract_version=lambda: container.api_contract_version,
        get_attachment_handler=lambda: container.get_attachment_handler,
        create_staged_attachment_handler=lambda: container.create_staged_attachment_handler,
    )


AttachmentRouteDependency = Annotated[
    AttachmentRouteDependencies,
    Depends(get_attachment_route_dependencies),
]
