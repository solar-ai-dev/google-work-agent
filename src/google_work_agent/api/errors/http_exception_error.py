"""Translate FastAPI HTTP exceptions to the Local API error contract."""

from fastapi import HTTPException

from google_work_agent.api.errors.api_request_error import ApiRequestError


def api_error_from_http(error: HTTPException, request_id: str) -> ApiRequestError:
    return ApiRequestError(
        error_code="INTERNAL_ERROR" if error.status_code >= 500 else "INVALID_ARGUMENT",
        user_message=str(error.detail),
        status_code=error.status_code,
        request_id=request_id,
    )
