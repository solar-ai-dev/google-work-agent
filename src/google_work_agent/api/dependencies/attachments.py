"""Attachment route dependency contract and provider."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.application.attachments import (
    GetGmailAttachmentService,
    StageAttachmentService,
)


@dataclass(frozen=True, slots=True)
class AttachmentRouteDependencies:
    api_contract_version: Callable[[], str]
    get_gmail_attachment_service: Callable[[], GetGmailAttachmentService | None]
    stage_attachment_service: Callable[[], StageAttachmentService | None]


def get_attachment_route_dependencies(request: Request) -> AttachmentRouteDependencies:
    container = get_api_container(request)
    return AttachmentRouteDependencies(
        api_contract_version=lambda: container.api_contract_version,
        get_gmail_attachment_service=lambda: container.get_gmail_attachment_service,
        stage_attachment_service=lambda: container.stage_attachment_service,
    )


AttachmentRouteDependency = Annotated[
    AttachmentRouteDependencies,
    Depends(get_attachment_route_dependencies),
]
