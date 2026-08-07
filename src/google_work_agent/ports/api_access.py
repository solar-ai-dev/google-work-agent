"""API access guard contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class EndpointPolicy(StrEnum):
    """High-level access policy categories for API endpoints."""

    HEALTH_PUBLIC = "HEALTH_PUBLIC"
    API_SESSION_REQUIRED = "API_SESSION_REQUIRED"
    BOOTSTRAP_EXCHANGE = "BOOTSTRAP_EXCHANGE"
    OAUTH_CALLBACK = "OAUTH_CALLBACK"


@dataclass(frozen=True, slots=True)
class ApiRequestContext:
    """Request context exposed to the access guard."""

    method: str
    path: str
    request_id: str
    client_host: str | None
    host: str | None = None
    origin: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    session_token: str | None = None
    sec_fetch_site: str | None = None
    sec_fetch_mode: str | None = None
    sec_fetch_dest: str | None = None


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Authorization decision for one request."""

    allowed: bool
    status_code: int = 200
    error_code: str | None = None
    user_message: str | None = None
    detail_code: str | None = None
    retryable: bool = False


class ApiAccessGuard(Protocol):
    """Authorize API requests without tying the core to one auth mechanism."""

    def authorize(
        self,
        request_context: ApiRequestContext,
        *,
        endpoint_policy: EndpointPolicy,
    ) -> AccessDecision:
        """Return the authorization decision for one endpoint invocation."""
