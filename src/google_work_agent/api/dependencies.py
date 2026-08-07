"""FastAPI dependency helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from fastapi import Request

from google_work_agent.api.errors import ApiError
from google_work_agent.ports import AccessDecision, ApiRequestContext, EndpointPolicy

if TYPE_CHECKING:
    from google_work_agent.api.app import ApiContainer


def get_container(request: Request) -> ApiContainer:
    """Return the application container stored on `app.state`."""

    return cast("ApiContainer", request.app.state.container)


def get_request_id(request: Request) -> str:
    """Return the per-request identifier."""

    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    container = get_container(request)
    request_id = container.id_generator.next_id()
    request.state.request_id = request_id
    return request_id


def enforce_api_contract_version(
    *,
    container: ApiContainer,
    request_id: str,
    request_version: str | None,
) -> None:
    """Reject unsupported contract versions before application execution."""

    if request_version is None:
        return
    if request_version != container.api_contract_version:
        raise ApiError(
            error_code="VERSION_CONFLICT",
            user_message="지원하지 않는 API 계약 버전입니다.",
            status_code=409,
            request_id=request_id,
            detail_code="API_CONTRACT_VERSION_MISMATCH",
        )


def enforce_access(
    request: Request,
    *,
    policy: EndpointPolicy,
) -> None:
    """Authorize one request through the configured access guard."""

    container = get_container(request)
    request_id = get_request_id(request)
    decision = container.api_access_guard.authorize(
        ApiRequestContext(
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client_host=None if request.client is None else request.client.host,
        ),
        endpoint_policy=policy,
    )
    _raise_if_denied(decision, request_id)


def _raise_if_denied(decision: AccessDecision, request_id: str) -> None:
    if decision.allowed:
        return
    raise ApiError(
        error_code=decision.error_code or "LOCAL_SESSION_INVALID",
        user_message=decision.user_message or "요청이 허용되지 않았습니다.",
        status_code=decision.status_code,
        request_id=request_id,
        retryable=decision.retryable,
        detail_code=decision.detail_code,
    )
