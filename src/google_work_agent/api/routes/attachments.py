"""Gmail attachment download and outbound staging routes.

Both routes are local-session gated like every other mutating/reading Local
API endpoint. Neither route persists attachment bytes anywhere, logs them,
or hands them to an LLM/agent: the download route streams bytes straight to
the browser and discards them, and the staging route returns only an
AttachmentDescriptor (metadata + hash), never the bytes it just staged.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from google_work_agent.adapters.runtime.attachment_staging import AttachmentStagingError
from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.attachments import (
    AttachmentDescriptorResponse,
    StageAttachmentRequest,
)
from google_work_agent.ports import (
    EndpointPolicy,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
)

router = APIRouter(prefix="/api/v1")

_STAGING_ERROR_STATUS = {
    "ATTACHMENT_EMPTY": 422,
    "ATTACHMENT_TOO_LARGE": 413,
    "ATTACHMENT_FILENAME_INVALID": 422,
}


@router.get("/gmail/messages/{message_id}/attachments/{attachment_id}")
def download_gmail_attachment(
    message_id: str,
    attachment_id: str,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> StreamingResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.get_gmail_attachment_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Attachment provider is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="ATTACHMENT_SERVICE_UNAVAILABLE",
        )
    try:
        attachment = service(message_id=message_id, attachment_id=attachment_id)
    except GoogleWorkspaceGatewayError as error:
        _raise_attachment_gateway_error(error, request_id=request.state.request_id)
    return StreamingResponse(
        iter([attachment.data]),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(attachment.size_bytes),
            "Content-Disposition": "attachment",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/attachments/stage", response_model=AttachmentDescriptorResponse)
def stage_attachment(
    body: StageAttachmentRequest,
    request: Request,
    x_api_contract_version: str | None = Header(default=None),
) -> AttachmentDescriptorResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    service = container.stage_attachment_service
    if service is None:
        raise ApiError(
            error_code="SERVICE_BUSY",
            user_message="Attachment staging is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="ATTACHMENT_STAGING_SERVICE_UNAVAILABLE",
        )
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except binascii.Error as error:
        raise ApiError(
            error_code="INVALID_ATTACHMENT",
            user_message="The attachment could not be staged.",
            status_code=422,
            request_id=request.state.request_id,
            detail_code="ATTACHMENT_ENCODING_INVALID",
        ) from error
    try:
        descriptor = service(data=data, filename=body.filename, mime_type=body.mime_type)
    except AttachmentStagingError as error:
        raise ApiError(
            error_code="INVALID_ATTACHMENT",
            user_message="The attachment could not be staged.",
            status_code=_STAGING_ERROR_STATUS.get(error.safe_code, 422),
            request_id=request.state.request_id,
            detail_code=error.safe_code,
        ) from error
    return AttachmentDescriptorResponse(
        staged_attachment_id=descriptor.staged_attachment_id,
        filename=descriptor.filename,
        mime_type=descriptor.mime_type,
        size_bytes=descriptor.size_bytes,
        sha256=descriptor.sha256,
        api_contract_version=container.api_contract_version,
    )


def _raise_attachment_gateway_error(error: GoogleWorkspaceGatewayError, *, request_id: str) -> None:
    mapping = {
        GoogleWorkspaceErrorCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422, False),
        GoogleWorkspaceErrorCode.AUTH_EXPIRED: ("AUTH_REQUIRED", 401, False),
        GoogleWorkspaceErrorCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403, False),
        GoogleWorkspaceErrorCode.NOT_FOUND: ("NOT_FOUND", 404, False),
        GoogleWorkspaceErrorCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429, True),
        GoogleWorkspaceErrorCode.UPSTREAM_5XX: ("UPSTREAM_UNAVAILABLE", 502, True),
        GoogleWorkspaceErrorCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504, True),
        GoogleWorkspaceErrorCode.CONNECTION_CLOSED: ("SERVICE_BUSY", 503, True),
        GoogleWorkspaceErrorCode.RESPONSE_MALFORMED: ("UPSTREAM_UNAVAILABLE", 502, False),
    }
    error_code, status_code, retryable = mapping.get(
        error.code,
        ("UPSTREAM_UNAVAILABLE", 502, False),
    )
    raise ApiError(
        error_code=error_code,
        user_message="Google attachment request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=retryable,
        detail_code=f"GOOGLE_{error.code.value}",
    ) from error
