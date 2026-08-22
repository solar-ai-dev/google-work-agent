"""Register the Local API error-envelope translation boundary."""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from google_work_agent.api.container import ApiContainer
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.errors.http_exception_error import api_error_from_http
from google_work_agent.api.errors.request_validation_error import api_error_from_validation


def install_error_response_handlers(app: FastAPI, container: ApiContainer) -> None:
    @app.exception_handler(ApiRequestError)
    async def api_error_handler(_: Request, error: ApiRequestError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error_code": error.error_code,
                "user_message": error.user_message,
                "retryable": error.retryable,
                "current_state": error.current_state,
                "request_id": error.request_id,
                "detail_code": error.detail_code,
                "api_contract_version": container.api_contract_version,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        api_error = api_error_from_validation(error, request.state.request_id)
        return await api_error_handler(request, api_error)

    @app.exception_handler(Exception)
    async def fallback_error_handler(request: Request, error: Exception) -> JSONResponse:
        if isinstance(error, HTTPException):
            api_error = api_error_from_http(error, request.state.request_id)
        else:
            api_error = ApiRequestError(
                error_code="INTERNAL_ERROR",
                user_message="처리 중 오류가 발생했습니다.",
                status_code=500,
                request_id=request.state.request_id,
            )
        return await api_error_handler(request, api_error)
