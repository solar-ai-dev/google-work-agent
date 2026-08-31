"""Attachment route dependency contract and provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentHandler,
)
from google_work_agent.application.use_cases.attachment.get_attachment import GetAttachmentHandler


@dataclass(frozen=True, slots=True)
class AttachmentRouteDependencies:
    api_contract_version: str
    get_attachment_handler: GetAttachmentHandler | None
    create_staged_attachment_handler: CreateStagedAttachmentHandler | None
    max_attachment_bytes: int


def get_attachment_route_dependencies(request: Request) -> AttachmentRouteDependencies:
    container = get_api_container(request)
    return AttachmentRouteDependencies(
        api_contract_version=container.api_contract_version,
        get_attachment_handler=container.get_attachment_handler,
        create_staged_attachment_handler=container.create_staged_attachment_handler,
        max_attachment_bytes=container.max_attachment_bytes,
    )


AttachmentRouteDependency = Annotated[
    AttachmentRouteDependencies,
    Depends(get_attachment_route_dependencies),
]
