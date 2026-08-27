"""Authorize requests through the configured Local API access policy."""

from fastapi import Request

from google_work_agent.api.dependencies.request_context import get_api_container
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.api.security.cookies import LOCAL_SESSION_COOKIE_NAME
from google_work_agent.ports import AccessDecision, ApiRequestContext, EndpointPolicy


def enforce_access(request: Request, *, policy: EndpointPolicy) -> None:
    container = get_api_container(request)
    request_id = _get_request_id(request)
    client_address_resolver = container.client_address_resolver
    client_host = (
        client_address_resolver(request)
        if client_address_resolver is not None
        else None
        if request.client is None
        else request.client.host
    )
    decision = container.api_access_guard.authorize(
        ApiRequestContext(
            method=request.method,
            path=request.url.path,
            request_id=request_id,
            client_host=client_host,
            host=request.headers.get("host"),
            origin=request.headers.get("origin"),
            content_type=request.headers.get("content-type"),
            content_length=_parse_content_length(request.headers.get("content-length")),
            session_token=request.cookies.get(LOCAL_SESSION_COOKIE_NAME),
            sec_fetch_site=request.headers.get("sec-fetch-site"),
            sec_fetch_mode=request.headers.get("sec-fetch-mode"),
            sec_fetch_dest=request.headers.get("sec-fetch-dest"),
        ),
        endpoint_policy=policy,
    )
    _raise_if_denied(decision, request_id)


def _get_request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str):
        return existing
    container = get_api_container(request)
    request_id = container.id_generator.new_uuid()
    request.state.request_id = request_id
    return request_id


def _parse_content_length(content_length: str | None) -> int | None:
    if content_length is None or not content_length.isdigit():
        return None
    return int(content_length)


def _raise_if_denied(decision: AccessDecision, request_id: str) -> None:
    if decision.allowed:
        return
    raise ApiRequestError(
        error_code=decision.error_code or "LOCAL_SESSION_INVALID",
        user_message=decision.user_message or "요청이 허용되지 않았습니다.",
        status_code=decision.status_code,
        request_id=request_id,
        retryable=decision.retryable,
        detail_code=decision.detail_code,
    )
