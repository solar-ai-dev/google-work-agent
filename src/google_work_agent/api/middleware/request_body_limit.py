"""Reject oversized mutation request bodies."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from google_work_agent.api.container import ApiContainer
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.security.body_limit import is_body_too_large


def install_request_body_limit_middleware(app: FastAPI, container: ApiContainer) -> None:
    @app.middleware("http")
    async def request_body_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            body = await request.body()
            content_length = request.headers.get("content-length")
            parsed_length = (
                int(content_length)
                if content_length is not None and content_length.isdigit()
                else None
            )
            limit_bytes = (
                container.max_attachment_bytes + 64 * 1024
                if request.url.path == "/api/v1/attachments/stage"
                else container.max_request_body_bytes
            )
            if is_body_too_large(
                content_length=parsed_length,
                actual_length=len(body),
                limit_bytes=limit_bytes,
            ):
                request_id = getattr(request.state, "request_id", None)
                if not isinstance(request_id, str):
                    request_id = container.id_generator.new_uuid()
                raise ApiRequestError(
                    error_code="INVALID_ARGUMENT",
                    user_message="Request body exceeds the local API limit.",
                    status_code=413,
                    request_id=request_id,
                    detail_code="REQUEST_BODY_TOO_LARGE",
                )
        return await call_next(request)
