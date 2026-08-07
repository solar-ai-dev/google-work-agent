"""Common API error mapping."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError

from google_work_agent.domain import ResultCode


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    """Structured API exception translated into the common error envelope."""

    error_code: str
    user_message: str
    status_code: int
    request_id: str
    retryable: bool = False
    current_state: str | None = None
    detail_code: str | None = None


def http_status_for_result_code(result_code: str, *, default_success: int = 200) -> int:
    """Map product result codes to HTTP status codes."""

    code = ResultCode(result_code) if result_code in ResultCode._value2member_map_ else None
    if code is ResultCode.VERSION_CONFLICT:
        return 409
    if code is ResultCode.DUPLICATE_COMMAND:
        return 409
    if code is ResultCode.STATE_CONFLICT:
        return 409
    if code is ResultCode.RECOVERY_REQUIRED:
        return 409
    return default_success


def error_code_for_result_code(result_code: str) -> str:
    """Map domain result codes to API error codes."""

    mapping = {
        ResultCode.VERSION_CONFLICT.value: "VERSION_CONFLICT",
        ResultCode.DUPLICATE_COMMAND.value: "DUPLICATE_COMMAND",
        ResultCode.STATE_CONFLICT.value: "STATE_CONFLICT",
        ResultCode.RECOVERY_REQUIRED.value: "RECOVERY_REQUIRED",
    }
    return mapping.get(result_code, "INTERNAL_ERROR")


def api_error_from_validation(error: RequestValidationError, request_id: str) -> ApiError:
    """Translate FastAPI validation errors."""

    return ApiError(
        error_code="INVALID_ARGUMENT",
        user_message="잘못된 요청입니다.",
        status_code=422,
        request_id=request_id,
        detail_code="REQUEST_VALIDATION_FAILED",
    )


def api_error_from_http(error: HTTPException, request_id: str) -> ApiError:
    """Translate FastAPI HTTP exceptions."""

    return ApiError(
        error_code="INTERNAL_ERROR" if error.status_code >= 500 else "INVALID_ARGUMENT",
        user_message=str(error.detail),
        status_code=error.status_code,
        request_id=request_id,
    )
