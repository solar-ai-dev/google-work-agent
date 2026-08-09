"""Local MCP child process for Google OAuth credentials.

Google Workspace resource adapters deliberately do not live in this module yet.
This process owns the Desktop OAuth loopback flow and the OS-keyring refresh token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.mcp.transport import PROTOCOL_VERSION
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import CredentialState, OAuthEnvironment, SecretStore

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_KEYRING_SERVICE = "GoogleWorkAgent/DEVELOPMENT"
GOOGLE_REFRESH_TOKEN_ACCOUNT = "google-oauth-refresh-token"
REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
)
OAUTH_FLOW_TTL_MS = 60_000
DEFAULT_ACCESS_TOKEN_TTL_MS = 3_600_000


@dataclass(frozen=True, slots=True)
class _OAuthFlow:
    flow_id: str
    state: str
    verifier: str
    callback_url: str
    expires_at_ms: int
    client_id: str


class _OAuthConfigurationError(RuntimeError):
    """Raised when local OAuth configuration is incomplete."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class _OAuthExchangeError(RuntimeError):
    """Raised when Google's token endpoint rejects a callback code."""

    def __init__(
        self,
        safe_error_code: str = "TOKEN_EXCHANGE_FAILED",
        safe_error_description: str | None = None,
    ) -> None:
        super().__init__(safe_error_code)
        self.safe_error_code = safe_error_code
        self.safe_error_description = safe_error_description


class _OAuthReauthenticationRequired(RuntimeError):
    """Raised when Google rejects a stored refresh token."""


class _WorkspaceToolsNotImplemented(RuntimeError):
    """Raised until real Gmail/Calendar/Tasks adapters are implemented."""


class _WorkspaceState:
    def __init__(self, *, keyring: SecretStore | None = None) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        self.connection_state = CredentialState.NOT_CONNECTED
        self.account_email: str | None = None
        self.display_name: str | None = None
        # Access tokens are intentionally process-memory-only.
        self.access_token: str | None = None
        self.access_token_expires_at_ms = 0
        self._refresh_lock = threading.Lock()
        self._oauth_flow_lock = threading.Lock()
        self.last_checked_at_ms = _now_ms()
        self.last_oauth_error_code: str | None = None
        self.last_oauth_error_description: str | None = None
        self.active_flow: _OAuthFlow | None = None
        self.oauth_settings = GoogleOAuthSettings.load(
            runtime_environment=os.environ.get("GWA_MCP_ENVIRONMENT", ""),
        )
        self.keyring = keyring or OSKeyringSecretStore()
        if (
            self.keyring.get_secret(
                service=GOOGLE_KEYRING_SERVICE,
                account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
            )
            is not None
        ):
            self.connection_state = CredentialState.CONNECTED

    def connection_payload(self) -> dict[str, object]:
        connected = self.connection_state is CredentialState.CONNECTED
        return {
            "connected": connected,
            "credential_state": self.connection_state.value,
            "account_email": self.account_email,
            "display_name": self.display_name,
            "granted_scopes": list(REQUIRED_SCOPES) if connected else [],
            "missing_scopes": [],
            "reauth_required": self.connection_state is CredentialState.REAUTH_REQUIRED,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "last_checked_at_ms": self.last_checked_at_ms,
            "safe_error_code": self.last_oauth_error_code,
            "safe_error_description": self.last_oauth_error_description,
        }

    def ensure_access_token(self) -> None:
        if self.access_token is not None and _now_ms() < self.access_token_expires_at_ms:
            return
        with self._refresh_lock:
            if self.access_token is not None and _now_ms() < self.access_token_expires_at_ms:
                return
            refresh_token = self.keyring.get_secret(
                service=GOOGLE_KEYRING_SERVICE,
                account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
            )
            if refresh_token is None:
                self.connection_state = CredentialState.NOT_CONNECTED
                return
            access_token, expires_at_ms, rotated_refresh_token = _refresh_access_token(
                refresh_token,
                self.oauth_settings.google_oauth_client_id,
                self.oauth_settings.google_oauth_client_secret,
            )
            self.access_token = access_token
            self.access_token_expires_at_ms = expires_at_ms
            if rotated_refresh_token is not None:
                self.keyring.set_secret(
                    service=GOOGLE_KEYRING_SERVICE,
                    account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
                    secret=rotated_refresh_token,
                )
            self.connection_state = CredentialState.CONNECTED


def main() -> None:
    try:
        state = _WorkspaceState()
    except RuntimeError:
        # Do not disclose keyring implementation details or credential material.
        state = None
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        if str(request.get("type")) == "shutdown":
            break
        if state is None:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": "OS keyring is unavailable.",
                    },
                }
            )
            continue
        try:
            _write({"id": request_id, "payload": _dispatch(state, request)})
        except _OAuthConfigurationError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": error.safe_code,
                    },
                }
            )
        except _OAuthExchangeError:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": "Google OAuth token exchange failed.",
                    },
                }
            )
        except _WorkspaceToolsNotImplemented:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": "Google Workspace tools are not implemented.",
                    },
                }
            )
        except KeyError as error:
            _write({"id": request_id, "error": {"code": "NOT_FOUND", "message": str(error)}})
        except Exception:
            _write(
                {
                    "id": request_id,
                    "error": {"code": "MALFORMED_RESPONSE", "message": "MCP request failed."},
                }
            )


def _dispatch(state: _WorkspaceState, request: dict[str, object]) -> dict[str, object]:
    message_type = str(request["type"])
    if message_type == "handshake":
        session_key = str(request["session_key"])
        if len(bytes.fromhex(session_key)) < 32:
            raise ValueError("session key must be at least 256 bits")
        state.service_instance_id = str(request["service_instance_id"])
        state.session_key = session_key
        return {"process_instance_id": state.process_instance_id}
    if message_type == "initialize":
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "tool_registry_version": str(request["tool_registry_version"]),
        }
    if message_type == "list_tools":
        return {
            "tool_names": sorted(
                entry.tool_name for entry in build_p0_tool_registry().list_entries()
            )
        }
    if message_type == "control_call":
        return _control_call(state, method=str(request["method"]))
    if message_type == "tool_call":
        raise _WorkspaceToolsNotImplemented
    raise ValueError("unsupported message type")


def _control_call(state: _WorkspaceState, *, method: str) -> dict[str, object]:
    if method == "google.connection.get":
        try:
            state.ensure_access_token()
        except _OAuthReauthenticationRequired:
            state.connection_state = CredentialState.REAUTH_REQUIRED
            state.access_token = None
            state.access_token_expires_at_ms = 0
        state.last_checked_at_ms = _now_ms()
        return state.connection_payload()
    if method == "google.connection.disconnect":
        refresh_token = state.keyring.get_secret(
            service=GOOGLE_KEYRING_SERVICE,
            account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
        )
        revoke_succeeded = (
            _revoke_refresh_token(refresh_token) if refresh_token is not None else False
        )
        deleted = state.keyring.delete_secret(
            service=GOOGLE_KEYRING_SERVICE, account=GOOGLE_REFRESH_TOKEN_ACCOUNT
        )
        state.connection_state = CredentialState.NOT_CONNECTED
        state.access_token = None
        state.access_token_expires_at_ms = 0
        state.account_email = None
        state.display_name = None
        state.last_checked_at_ms = _now_ms()
        return {
            "disconnected": True,
            "credential_deleted": deleted,
            "revoke_attempted": refresh_token is not None,
            "revoke_succeeded": revoke_succeeded,
            "credential_state": state.connection_state.value,
        }
    if method == "google.oauth.start":
        if state.oauth_settings.google_oauth_client_id is None:
            raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
        if state.oauth_settings.google_oauth_client_secret is None:
            raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
        if state.active_flow is not None and state.active_flow.expires_at_ms > _now_ms():
            raise ValueError("oauth flow already active")
        flow = _start_oauth_flow(state)
        state.last_oauth_error_code = None
        state.last_oauth_error_description = None
        state.active_flow = flow
        return {
            "flow_id": flow.flow_id,
            "authorization_url": _authorization_url(flow),
            "callback_url": flow.callback_url,
            "expires_at_ms": flow.expires_at_ms,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "scopes": list(REQUIRED_SCOPES),
        }
    raise ValueError("unsupported control method")


def _start_oauth_flow(state: _WorkspaceState) -> _OAuthFlow:
    oauth_state = secrets.token_urlsafe(24)
    server = _OAuthCallbackServer(state=state, expected_state=oauth_state)
    callback_url = server.start()
    return _OAuthFlow(
        flow_id=f"flow-{secrets.token_hex(8)}",
        state=oauth_state,
        verifier=secrets.token_urlsafe(48),
        callback_url=callback_url,
        expires_at_ms=_now_ms() + OAUTH_FLOW_TTL_MS,
        client_id=state.oauth_settings.google_oauth_client_id or "",
    )


def _authorization_url(flow: _OAuthFlow) -> str:
    # The API returns only a loopback URL.  The client ID is never sent in an API payload.
    parsed = urlparse(flow.callback_url)
    loopback_origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{loopback_origin}/oauth/authorize?{urlencode({'state': flow.state})}"


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _google_authorization_url(flow: _OAuthFlow) -> str:
    query = urlencode(
        {
            "client_id": flow.client_id,
            "redirect_uri": flow.callback_url,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES),
            "state": flow.state,
            "code_challenge_method": "S256",
            "code_challenge": _pkce_s256(flow.verifier),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"


def _exchange_authorization_code(
    flow: _OAuthFlow,
    code: str,
    client_secret: str | None,
) -> tuple[str, str | None]:
    if client_secret is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
    body = urlencode(
        {
            "client_id": flow.client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": flow.verifier,
            "grant_type": "authorization_code",
            "redirect_uri": flow.callback_url,
        }
    ).encode("ascii")
    request = Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google endpoint
            payload = cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        raise _oauth_exchange_error_from_http_error(
            error,
            sensitive_values=(
                flow.client_id,
                client_secret,
                code,
                flow.verifier,
                flow.state,
                flow.callback_url,
            ),
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise _OAuthExchangeError from error
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise _OAuthExchangeError
    access_token = payload.get("access_token")
    return refresh_token, access_token if isinstance(access_token, str) else None


def _oauth_exchange_error_from_http_error(
    error: HTTPError,
    *,
    sensitive_values: tuple[str, ...],
) -> _OAuthExchangeError:
    try:
        payload = cast(dict[str, object], json.loads(error.read().decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _OAuthExchangeError(f"TOKEN_EXCHANGE_HTTP_{error.code}")
    provider_error = payload.get("error")
    safe_description = _redact_provider_error_description(
        payload.get("error_description"),
        sensitive_values=sensitive_values,
    )
    if provider_error == "invalid_grant":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_GRANT",
            safe_description
            or "Google rejected the authorization code or its PKCE/redirect binding.",
        )
    if provider_error == "invalid_client":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_CLIENT",
            safe_description or "Google rejected the configured desktop OAuth client.",
        )
    if provider_error == "redirect_uri_mismatch":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_REDIRECT_URI_MISMATCH",
            safe_description or "Google rejected the loopback redirect URI binding.",
        )
    if provider_error == "invalid_request":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_REQUEST",
            safe_description or "Google rejected the token request.",
        )
    return _OAuthExchangeError(f"TOKEN_EXCHANGE_HTTP_{error.code}", safe_description)


def _redact_provider_error_description(
    value: object, *, sensitive_values: tuple[str, ...]
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    redacted = value
    for sensitive_value in sensitive_values:
        if sensitive_value:
            redacted = redacted.replace(sensitive_value, "[REDACTED]")
    redacted = re.sub(
        r"(?i)\b(code|token|verifier|state|secret)=([^\s&,]+)",
        r"\1=[REDACTED]",
        redacted,
    )
    normalized = " ".join(redacted.split())
    return normalized[:240] or None


def _refresh_access_token(
    refresh_token: str,
    client_id: str | None,
    client_secret: str | None,
) -> tuple[str, int, str | None]:
    if client_id is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
    if client_secret is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("ascii")
    request = Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google endpoint
            payload = cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        if error.code == 400:
            raise _OAuthReauthenticationRequired from error
        raise _OAuthExchangeError from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise _OAuthExchangeError from error
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _OAuthExchangeError
    expires_in = payload.get("expires_in")
    ttl_ms = int(expires_in) * 1000 if isinstance(expires_in, int) else DEFAULT_ACCESS_TOKEN_TTL_MS
    rotated = payload.get("refresh_token")
    return access_token, _now_ms() + ttl_ms, rotated if isinstance(rotated, str) else None


def _revoke_refresh_token(refresh_token: str) -> bool:
    request = Request(
        GOOGLE_REVOKE_ENDPOINT,
        data=urlencode({"token": refresh_token}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10):  # nosec B310: fixed Google endpoint
            return True
    except (HTTPError, URLError, TimeoutError):
        return False


class _OAuthCallbackServer:
    def __init__(self, *, state: _WorkspaceState, expected_state: str) -> None:
        self._state = state
        self._expected_state = expected_state
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                state_value = params.get("state", [""])[0]
                if not hmac.compare_digest(state_value, outer._expected_state):
                    self._respond(400, b"state mismatch")
                    outer._finish_flow()
                    return
                if parsed.path == "/oauth/authorize":
                    flow = outer._state.active_flow
                    if flow is None:
                        self._respond(400, b"oauth flow unavailable")
                        outer._finish_flow()
                        return
                    self.send_response(302)
                    self.send_header("Location", _google_authorization_url(flow))
                    self.end_headers()
                    return
                if parsed.path != "/oauth/callback":
                    self._respond(404, b"not found")
                    outer._finish_flow()
                    return
                code = params.get("code", [""])[0]
                with outer._state._oauth_flow_lock:
                    flow = outer._state.active_flow
                    if code and flow is not None and flow.expires_at_ms > _now_ms():
                        outer._state.active_flow = None
                    else:
                        flow = None
                if flow is None:
                    self._respond(400, b"oauth flow expired")
                    return
                try:
                    refresh_token, access_token = _exchange_authorization_code(
                        flow,
                        code,
                        outer._state.oauth_settings.google_oauth_client_secret,
                    )
                    outer._state.keyring.set_secret(
                        service=GOOGLE_KEYRING_SERVICE,
                        account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
                        secret=refresh_token,
                    )
                except _OAuthExchangeError as error:
                    outer._state.last_oauth_error_code = error.safe_error_code
                    outer._state.last_oauth_error_description = error.safe_error_description
                    self._respond(
                        502,
                        f"Google OAuth token exchange failed: {error.safe_error_code}".encode(),
                    )
                    outer._finish_flow()
                    return
                outer._state.access_token = access_token
                outer._state.access_token_expires_at_ms = _now_ms() + DEFAULT_ACCESS_TOKEN_TTL_MS
                outer._state.connection_state = CredentialState.CONNECTED
                outer._state.last_checked_at_ms = _now_ms()
                outer._state.last_oauth_error_code = None
                outer._state.last_oauth_error_description = None
                self._respond(200, b"Google account connected. You can close this window.")
                outer._shutdown()

            def _respond(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                del format, args

        return Handler

    def start(self) -> str:
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}/oauth/callback"

    def _finish_flow(self) -> None:
        self._state.active_flow = None
        self._shutdown()

    def _shutdown(self) -> None:
        threading.Thread(target=self._server.shutdown, daemon=True).start()


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    main()
