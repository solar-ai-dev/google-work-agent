"""Gmail attachment download and outbound staging routes."""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.attachments import (
    AttachmentRouteDependencies,
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
from google_work_agent.application.use_cases.attachment.fetch_attachment import (
    FetchAttachmentHandler,
    FetchAttachmentQuery,
)
from google_work_agent.application.use_cases.attachment.stage_attachment import (
    StageAttachmentCommand,
    StageAttachmentHandler,
)
from google_work_agent.ports import EndpointPolicy
from google_work_agent.ports.connectors.failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)

_STAGING_ERROR_STATUS = {
    "ATTACHMENT_EMPTY": 422,
    "ATTACHMENT_TOO_LARGE": 413,
    "ATTACHMENT_FILENAME_INVALID": 422,
}


def create_router(dependencies: AttachmentRouteDependencies | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/gmail/messages/{message_id}/attachments/{attachment_id}")
    def download_gmail_attachment(
        message_id: str,
        attachment_id: str,
        request: Request,
        injected_dependencies: AttachmentRouteDependency,
        x_api_contract_version: str | None = Header(default=None),
    ) -> StreamingResponse:
        route_dependencies = dependencies or injected_dependencies
        enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
        enforce_supported_api_contract_version(
            supported_version=route_dependencies.api_contract_version(),
            request_id=request.state.request_id,
            request_version=x_api_contract_version,
        )
        service = route_dependencies.get_gmail_attachment_service()
        if service is None:
            raise ApiRequestError(
                error_code="SERVICE_BUSY",
                user_message="Attachment provider is not configured.",
                status_code=503,
                request_id=request.state.request_id,
                detail_code="ATTACHMENT_SERVICE_UNAVAILABLE",
            )
        try:
            result = FetchAttachmentHandler(service)(
                FetchAttachmentQuery(message_id=message_id, attachment_id=attachment_id)
            )
        except ConnectorOperationFailure as error:
            _raise_attachment_failure(error, request_id=request.state.request_id)
        attachment = result.attachment
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
        injected_dependencies: AttachmentRouteDependency,
        x_api_contract_version: str | None = Header(default=None),
    ) -> AttachmentDescriptorResponse:
        route_dependencies = dependencies or injected_dependencies
        enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
        supported_version = route_dependencies.api_contract_version()
        enforce_supported_api_contract_version(
            supported_version=supported_version,
            request_id=request.state.request_id,
            request_version=x_api_contract_version,
        )
        service = route_dependencies.stage_attachment_service()
        if service is None:
            raise ApiRequestError(
                error_code="SERVICE_BUSY",
                user_message="Attachment staging is not configured.",
                status_code=503,
                request_id=request.state.request_id,
                detail_code="ATTACHMENT_STAGING_SERVICE_UNAVAILABLE",
            )
        try:
            data = base64.b64decode(body.data_base64, validate=True)
        except binascii.Error as error:
            raise ApiRequestError(
                error_code="INVALID_ATTACHMENT",
                user_message="The attachment could not be staged.",
                status_code=422,
                request_id=request.state.request_id,
                detail_code="ATTACHMENT_ENCODING_INVALID",
            ) from error
        try:
            result = StageAttachmentHandler(service)(
                StageAttachmentCommand(
                    data=data,
                    filename=body.filename,
                    mime_type=body.mime_type,
                )
            )
        except ConnectorOperationFailure as error:
            _raise_attachment_failure(error, request_id=request.state.request_id)
        descriptor = result.descriptor
        return AttachmentDescriptorResponse(
            staged_attachment_id=descriptor.staged_attachment_id,
            filename=descriptor.filename,
            mime_type=descriptor.mime_type,
            size_bytes=descriptor.size_bytes,
            sha256=descriptor.sha256,
            api_contract_version=supported_version,
        )

    return router


router = create_router()


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
