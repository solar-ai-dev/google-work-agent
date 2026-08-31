"""Local Session bootstrap route."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.sessions import SessionRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.schemas.sessions.bootstrap_session import (
    BootstrapSessionRequest,
    BootstrapSessionResponse,
)
from google_work_agent.api.security.cookies import local_session_cookie_name
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1/session")


@router.post("/bootstrap", response_model=BootstrapSessionResponse, status_code=status.HTTP_200_OK)
def bootstrap_session(
    request: Request,
    payload: BootstrapSessionRequest,
    response: Response,
    dependencies: SessionRouteDependency,
) -> BootstrapSessionResponse:
    enforce_access(request, policy=EndpointPolicy.BOOTSTRAP_EXCHANGE)
    service = dependencies.bootstrap_session_service
    if service is None:
        raise ApiRequestError(
            error_code="INTERNAL_ERROR",
            user_message="Bootstrap is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="BOOTSTRAP_NOT_CONFIGURED",
        )
    result = service.establish(
        bootstrap_secret=payload.bootstrap_secret,
        frontend_api_contract_version=payload.frontend_api_contract_version,
        now_ms=dependencies.clock.now_ms(),
    )
    if not result.allowed or result.session_token is None or result.compatibility is None:
        raise ApiRequestError(
            error_code="LOCAL_SESSION_INVALID",
            user_message="Bootstrap exchange rejected.",
            status_code=401,
            request_id=request.state.request_id,
            detail_code=result.detail_code,
        )
    response.set_cookie(
        key=local_session_cookie_name(dependencies.service_instance_id),
        value=result.session_token,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return BootstrapSessionResponse(
        session_established=True,
        service_instance_id=dependencies.service_instance_id,
        api_contract_version=dependencies.api_contract_version,
        compatibility=result.compatibility,
    )
