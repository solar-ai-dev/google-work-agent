"""Fetch attachment bytes through the Application connector boundary."""

from dataclasses import dataclass
from typing import Any

from google_work_agent.application.ports.connector_failure import (
    normalize_google_workspace_failure,
)
from google_work_agent.ports import GoogleWorkspaceGatewayError


@dataclass(frozen=True, slots=True)
class FetchAttachmentQuery:
    message_id: str
    attachment_id: str


@dataclass(frozen=True, slots=True)
class FetchAttachmentResult:
    attachment: Any


@dataclass(frozen=True, slots=True)
class FetchAttachmentHandler:
    service: Any

    def __call__(self, query: FetchAttachmentQuery) -> FetchAttachmentResult:
        try:
            attachment = self.service(
                message_id=query.message_id,
                attachment_id=query.attachment_id,
            )
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        return FetchAttachmentResult(attachment=attachment)
