"""Authenticated fallback for unknown versioned Local API paths."""

from fastapi import APIRouter, Request, Response

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter()


@router.api_route(
    "/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
)
async def reject_unknown_api_path(request: Request, path: str) -> Response:
    del path
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    raise ApiRequestError(
        error_code="NOT_FOUND",
        user_message="Route not found.",
        status_code=404,
        request_id=request.state.request_id,
        detail_code="API_ROUTE_NOT_FOUND",
    )
