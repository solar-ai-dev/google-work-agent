"""Get one external resource via the canonical resource_ref query boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from google_work_agent.ports.connectors.failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_google_workspace_failure,
)
from google_work_agent.ports import (
    GmailAttachmentMetadata,
    GmailThreadDetail,
    GoogleWorkspaceGatewayError,
)


@dataclass(frozen=True, slots=True)
class GmailResourceDetail:
    resource_id: str
    message_id: str
    sender_name: str | None
    sender_email: str | None
    recipients: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str | None
    received_at: str | None
    body: str | None
    attachments: tuple[GmailAttachmentMetadata, ...]
    canonical_url: str


class GetResourceAccess(Protocol):
    def get_gmail_thread_detail_raw(self, *, resource_id: str) -> GmailThreadDetail: ...


@dataclass(frozen=True, slots=True)
class GetResourceQuery:
    source: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class GetResourceResult:
    resource: GmailResourceDetail


@dataclass(frozen=True, slots=True)
class GetResourceHandler:
    access: GetResourceAccess

    def __call__(self, query: GetResourceQuery) -> GetResourceResult:
        if query.source != "gmail":
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.NOT_FOUND,
                detail_code="RESOURCE_SOURCE_NOT_FOUND",
            )
        try:
            detail = self.access.get_gmail_thread_detail_raw(resource_id=query.resource_id)
        except GoogleWorkspaceGatewayError as error:
            raise normalize_google_workspace_failure(error) from error
        except RuntimeError as error:
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.CONNECTION_UNAVAILABLE,
                detail_code="RESOURCE_DETAIL_UNAVAILABLE",
                retryable=True,
            ) from error
        return GetResourceResult(
            resource=GmailResourceDetail(
                resource_id=detail.thread_id,
                message_id=detail.message_id,
                sender_name=detail.sender_name,
                sender_email=detail.sender_email,
                recipients=detail.recipients,
                cc=detail.cc,
                subject=detail.subject,
                received_at=detail.received_at,
                body=detail.body,
                attachments=detail.attachments,
                canonical_url=_gmail_search_permalink(detail.rfc822_message_id),
            )
        )


def _gmail_search_permalink(rfc822_message_id: str | None) -> str:
    if not rfc822_message_id:
        return "https://mail.google.com/mail/u/0/#all"
    query = quote(f"rfc822msgid:{rfc822_message_id}", safe="")
    return f"https://mail.google.com/mail/u/0/#search/{query}"
