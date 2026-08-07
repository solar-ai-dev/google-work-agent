"""Local API access guard."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.api.security.content_type import is_allowed_json_content_type
from google_work_agent.api.security.fetch_metadata import (
    validate_fetch_metadata,
    validate_mutation_fetch_metadata,
)
from google_work_agent.api.security.origin import is_exact_origin_match
from google_work_agent.application.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
    append_operational_log,
    create_event_envelope,
)
from google_work_agent.ports import (
    AccessDecision,
    ApiRequestContext,
    EndpointPolicy,
    OperationalLogSink,
)

from .sessions import LocalSessionManager

_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True, slots=True)
class LocalApiAccessGuard:
    expected_host: str
    expected_origin: str
    service_instance_id: str
    session_manager: LocalSessionManager
    release_version: str
    environment: str
    now_ms: Callable[[], int]
    operational_log_sink: OperationalLogSink | None = None

    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        decision = self._authorize(request_context, endpoint_policy=endpoint_policy)
        if not decision.allowed and self.operational_log_sink is not None:
            envelope = create_event_envelope(
                event_name="LOCAL_API_REQUEST_DENIED",
                event_category=EventCategory.SECURITY,
                occurred_at_ms=self.now_ms(),
                severity=Severity.WARNING,
                component="api.security",
                environment=self.environment,
                release_version=self.release_version,
                correlation=ObservabilityContext(
                    service_instance_id=self.service_instance_id,
                    request_id=request_context.request_id,
                ),
                attributes={
                    "method": request_context.method,
                    "path": request_context.path,
                    "host": request_context.host,
                    "client_host": request_context.client_host,
                    "origin": request_context.origin,
                    "content_type": request_context.content_type,
                    "detail_code": decision.detail_code,
                    "endpoint_policy": endpoint_policy.value,
                    "has_session_cookie": request_context.session_token is not None,
                    "sec_fetch_site": request_context.sec_fetch_site,
                    "sec_fetch_mode": request_context.sec_fetch_mode,
                    "sec_fetch_dest": request_context.sec_fetch_dest,
                },
                result_code=decision.error_code,
                status="DENIED",
            )
            append_operational_log(self.operational_log_sink, envelope=envelope)
        return decision

    def _authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        if request_context.client_host != "127.0.0.1":
            return _deny(403, "LOCAL_ONLY", "CLIENT_NOT_LOOPBACK")
        if request_context.host != self.expected_host:
            return _deny(403, "LOCAL_ONLY", "HOST_HEADER_INVALID")
        method = request_context.method.upper()
        if endpoint_policy is EndpointPolicy.HEALTH_PUBLIC:
            if request_context.origin is not None and not is_exact_origin_match(
                request_context.origin,
                expected_origin=self.expected_origin,
            ):
                return _deny(403, "LOCAL_ONLY", "ORIGIN_INVALID")
            return AccessDecision(allowed=True)
        if method in _MUTATION_METHODS:
            if not is_exact_origin_match(
                request_context.origin,
                expected_origin=self.expected_origin,
            ):
                return _deny(403, "REQUEST_FORGERY_BLOCKED", "ORIGIN_REQUIRED")
            if not validate_mutation_fetch_metadata(
                site=request_context.sec_fetch_site,
                mode=request_context.sec_fetch_mode,
                destination=request_context.sec_fetch_dest,
            ):
                return _deny(403, "REQUEST_FORGERY_BLOCKED", "FETCH_METADATA_INVALID")
            if not is_allowed_json_content_type(request_context.content_type):
                return _deny(415, "INVALID_ARGUMENT", "CONTENT_TYPE_INVALID")
        else:
            if request_context.origin is not None and not is_exact_origin_match(
                request_context.origin,
                expected_origin=self.expected_origin,
            ):
                return _deny(403, "REQUEST_FORGERY_BLOCKED", "ORIGIN_INVALID")
            if not validate_fetch_metadata(
                site=request_context.sec_fetch_site,
                mode=request_context.sec_fetch_mode,
                destination=request_context.sec_fetch_dest,
                require_headers=request_context.path.startswith("/api/v1/"),
                allow_missing=not request_context.path.startswith("/api/v1/"),
            ):
                return _deny(403, "REQUEST_FORGERY_BLOCKED", "FETCH_METADATA_INVALID")
        if endpoint_policy is EndpointPolicy.API_SESSION_REQUIRED:
            is_valid_session = self.session_manager.validate(
                token=request_context.session_token,
                service_instance_id=self.service_instance_id,
            )
            if not is_valid_session:
                return _deny(401, "LOCAL_SESSION_INVALID", "LOCAL_SESSION_REQUIRED")
        return AccessDecision(allowed=True)


def _deny(status_code: int, error_code: str, detail_code: str) -> AccessDecision:
    return AccessDecision(
        allowed=False,
        status_code=status_code,
        error_code=error_code,
        user_message="Request rejected by local API security policy.",
        detail_code=detail_code,
    )
