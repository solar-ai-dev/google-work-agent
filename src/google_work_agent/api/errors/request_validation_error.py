"""Translate request-schema validation failures to the Local API error contract."""

from fastapi.exceptions import RequestValidationError

from google_work_agent.api.errors.api_request_error import ApiRequestError


def api_error_from_validation(
    error: RequestValidationError,
    request_id: str,
) -> ApiRequestError:
    del error
    return ApiRequestError(
        error_code="INVALID_ARGUMENT",
        user_message="잘못된 요청입니다.",
        status_code=422,
        request_id=request_id,
        detail_code="REQUEST_VALIDATION_FAILED",
    )
