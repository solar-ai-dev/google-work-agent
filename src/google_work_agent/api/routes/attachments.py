"""Gmail attachment download and outbound staging routes."""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import StreamingResponse

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.attachments import (
    AttachmentRouteDependency,
)
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.attachments.get_attachment import (
    AttachmentDescriptorResponse,
)
from google_work_agent.api.schemas.attachments.stage_attachment import StageAttachmentRequest
from google_work_agent.application.use_cases.attachment.create_staged_attachment import (
    CreateStagedAttachmentCommand,
    CreateStagedAttachmentHandler,
)
from google_work_agent.application.use_cases.attachment.get_attachment import (
    GetAttachmentHandler,
    GetAttachmentQuery,
)
from google_work_agent.application.use_cases.operational_replay import (
    OperationalCommandConflict,
    OperationalCommandUncertain,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

_STAGING_ERROR_STATUS = {
    "ATTACHMENT_EMPTY": 422,
    "ATTACHMENT_TOO_LARGE": 413,
    "ATTACHMENT_FILENAME_INVALID": 422,
    "ATTACHMENT_MIME_TYPE_INVALID": 422,
}


router = APIRouter(prefix="/api/v1")


@router.get("/gmail/messages/{message_id}/attachments/{attachment_id}")
def download_gmail_attachment(
    message_id: str,
    attachment_id: str,
    request: Request,
    dependencies: AttachmentRouteDependency,
    x_api_contract_version: str | None = Header(default=None),
) -> StreamingResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.get_attachment_handler
    if not isinstance(handler, GetAttachmentHandler):
        _raise_attachment_handler_unavailable(request, "ATTACHMENT_SERVICE_UNAVAILABLE")
    try:
        result = handler(GetAttachmentQuery(message_id=message_id, attachment_id=attachment_id))
    except ConnectorOperationFailure as error:
        _raise_attachment_failure(error, request_id=request.state.request_id)
    return StreamingResponse(
        iter([result.data]),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(result.size_bytes),
            "Content-Disposition": 'attachment; filename="attachment"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/attachments/stage", response_model=AttachmentDescriptorResponse)
async def stage_attachment(
    request: Request,
    dependencies: AttachmentRouteDependency,
    command_id: Annotated[str, Form(min_length=1, max_length=128)],
    file: Annotated[UploadFile, File()],
    x_api_contract_version: str | None = Header(default=None),
) -> AttachmentDescriptorResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    supported_version = dependencies.api_contract_version
    enforce_supported_api_contract_version(
        supported_version=supported_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    handler = dependencies.create_staged_attachment_handler
    if not isinstance(handler, CreateStagedAttachmentHandler):
        _raise_attachment_handler_unavailable(
            request,
            "ATTACHMENT_STAGING_SERVICE_UNAVAILABLE",
        )
    body = StageAttachmentRequest(command_id=command_id)
    data = await file.read(dependencies.max_attachment_bytes + 1)
    await file.close()
    if len(data) > dependencies.max_attachment_bytes:
        _raise_attachment_invalid(request, "ATTACHMENT_TOO_LARGE", 413)
    try:
        result = handler(
            CreateStagedAttachmentCommand(
                command_id=body.command_id,
                file_bytes=data,
                filename=file.filename or "",
                mime_type=file.content_type or "application/octet-stream",
            )
        )
    except OperationalCommandConflict as error:
        raise ApiRequestError(
            error_code="CONFLICT",
            user_message="The attachment command conflicts with an earlier request.",
            status_code=409,
            request_id=request.state.request_id,
            detail_code="ATTACHMENT_COMMAND_CONFLICT",
        ) from error
    except OperationalCommandUncertain as error:
        raise ApiRequestError(
            error_code="SERVICE_BUSY",
            user_message="The attachment staging result is not yet known.",
            status_code=503,
            request_id=request.state.request_id,
            retryable=True,
            detail_code="ATTACHMENT_STAGING_UNCERTAIN",
        ) from error
    except ConnectorOperationFailure as error:
        _raise_attachment_failure(error, request_id=request.state.request_id)
    descriptor = result.attachment
    return AttachmentDescriptorResponse(
        staged_attachment_id=descriptor.staged_attachment_id,
        filename=descriptor.filename,
        mime_type=descriptor.mime_type,
        size_bytes=descriptor.size_bytes,
        sha256=descriptor.sha256,
        expires_at_ms=descriptor.expires_at_ms,
        api_contract_version=supported_version,
    )


def _raise_attachment_handler_unavailable(request: Request, detail_code: str) -> NoReturn:
    raise ApiRequestError(
        error_code="SERVICE_BUSY",
        user_message="Attachment service is not configured.",
        status_code=503,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_attachment_invalid(request: Request, detail_code: str, status_code: int) -> NoReturn:
    raise ApiRequestError(
        error_code="INVALID_ATTACHMENT",
        user_message="The attachment could not be staged.",
        status_code=status_code,
        request_id=request.state.request_id,
        detail_code=detail_code,
    )


def _raise_attachment_failure(error: ConnectorOperationFailure, *, request_id: str) -> None:
    if error.code is ConnectorFailureCode.ATTACHMENT_INVALID:
        status_code = _STAGING_ERROR_STATUS.get(error.detail_code, 422)
        error_code = "INVALID_ATTACHMENT"
    else:
        mapping = {
            ConnectorFailureCode.INVALID_ARGUMENT: ("INVALID_ARGUMENT", 422),
            ConnectorFailureCode.AUTH_REQUIRED: ("AUTH_REQUIRED", 401),
            ConnectorFailureCode.PERMISSION_DENIED: ("PERMISSION_DENIED", 403),
            ConnectorFailureCode.NOT_FOUND: ("NOT_FOUND", 404),
            ConnectorFailureCode.RATE_LIMITED: ("UPSTREAM_UNAVAILABLE", 429),
            ConnectorFailureCode.UPSTREAM_UNAVAILABLE: ("UPSTREAM_UNAVAILABLE", 502),
            ConnectorFailureCode.TIMEOUT: ("UPSTREAM_UNAVAILABLE", 504),
            ConnectorFailureCode.CONNECTION_UNAVAILABLE: ("SERVICE_BUSY", 503),
            ConnectorFailureCode.MALFORMED_RESPONSE: ("UPSTREAM_UNAVAILABLE", 502),
        }
        error_code, status_code = mapping.get(
            error.code,
            ("UPSTREAM_UNAVAILABLE", 502),
        )
    raise ApiRequestError(
        error_code=error_code,
        user_message="Attachment request could not be completed.",
        status_code=status_code,
        request_id=request_id,
        retryable=error.retryable,
        detail_code=error.detail_code,
    ) from error
