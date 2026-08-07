"""Local session bootstrap route."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from google_work_agent.api.dependencies import (
    enforce_access,
    enforce_api_contract_version,
    get_container,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.api.schemas.session import BootstrapSessionRequest, BootstrapSessionResponse
from google_work_agent.api.security.cookies import LOCAL_SESSION_COOKIE_NAME
from google_work_agent.ports import EndpointPolicy

router = APIRouter(prefix="/api/v1/session")


@router.post("/bootstrap", response_model=BootstrapSessionResponse, status_code=status.HTTP_200_OK)
def bootstrap_session(
    request: Request,
    payload: BootstrapSessionRequest,
    response: Response,
) -> BootstrapSessionResponse:
    container = get_container(request)
    enforce_access(request, policy=EndpointPolicy.BOOTSTRAP_EXCHANGE)
    enforce_api_contract_version(
        container=container,
        request_id=request.state.request_id,
        request_version=payload.api_contract_version,
    )
    if payload.service_instance_id != container.service_instance_id:
        raise ApiError(
            error_code="INVALID_ARGUMENT",
            user_message="Service instance mismatch.",
            status_code=409,
            request_id=request.state.request_id,
            detail_code="SERVICE_INSTANCE_MISMATCH",
        )
    store = container.bootstrap_grant_store
    session_manager = container.local_session_manager
    if store is None or session_manager is None:
        raise ApiError(
            error_code="INTERNAL_ERROR",
            user_message="Bootstrap is not configured.",
            status_code=503,
            request_id=request.state.request_id,
            detail_code="BOOTSTRAP_NOT_CONFIGURED",
        )
    consume_result = store.consume(
        secret=payload.bootstrap_secret,
        service_instance_id=payload.service_instance_id,
        now_ms=container.clock.now_ms(),
    )
    if not consume_result.allowed:
        raise ApiError(
            error_code="LOCAL_SESSION_INVALID",
            user_message="Bootstrap exchange rejected.",
            status_code=401,
            request_id=request.state.request_id,
            detail_code=consume_result.detail_code,
        )
    token = session_manager.issue(
        service_instance_id=container.service_instance_id,
        now_ms=container.clock.now_ms(),
    )
    response.set_cookie(
        key=LOCAL_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return BootstrapSessionResponse(
        session_established=True,
        service_instance_id=container.service_instance_id,
        api_contract_version=container.api_contract_version,
    )
