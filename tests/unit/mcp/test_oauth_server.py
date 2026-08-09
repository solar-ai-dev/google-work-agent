from __future__ import annotations

import json
import threading
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
from urllib.request import Request, urlopen

import pytest

from google_work_agent.mcp import server
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import CredentialState


def _fake_id_token(claims: dict[str, object]) -> str:
    header = server._b64url_encode(b'{"alg":"RS256","typ":"JWT"}')
    payload = server._b64url_encode(json.dumps(claims).encode("utf-8"))
    return f"{header}.{payload}.unverified-signature"


def test_pkce_s256_matches_rfc_7636_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert server._pkce_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_required_scopes_include_openid_and_email() -> None:
    assert "openid" in server.REQUIRED_SCOPES
    assert "https://www.googleapis.com/auth/userinfo.email" in server.REQUIRED_SCOPES


def test_verified_email_from_id_token_extracts_verified_email() -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    assert server._verified_email_from_id_token(token) == "user@example.com"


def test_verified_email_from_id_token_rejects_unverified_email() -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": False})
    assert server._verified_email_from_id_token(token) is None


def test_verified_email_from_id_token_rejects_missing_email_verified_claim() -> None:
    token = _fake_id_token({"email": "user@example.com"})
    assert server._verified_email_from_id_token(token) is None


def test_verified_email_from_id_token_rejects_malformed_token() -> None:
    assert server._verified_email_from_id_token("not-a-jwt") is None
    assert server._verified_email_from_id_token("a.b") is None
    assert server._verified_email_from_id_token("a.!!!not-base64!!!.c") is None


def test_authorization_code_grant_binds_the_callback_uri_and_reports_only_redacted_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = server._OAuthFlow(
        flow_id="flow-1",
        state="state-value",
        verifier="verifier-value",
        callback_url="http://127.0.0.1:43123/oauth/callback",
        expires_at_ms=server._now_ms() + 60_000,
        client_id="desktop-client",
    )
    captured: Request | None = None

    def reject(request: Request, *, timeout: int) -> object:
        nonlocal captured
        del timeout
        captured = request
        raise HTTPError(
            server.GOOGLE_TOKEN_ENDPOINT,
            400,
            "Bad Request",
            hdrs=Message(),
            fp=BytesIO(
                b'{"error":"invalid_grant","error_description":"code=authorization-code '
                b'verifier=verifier-value client_secret=compatibility-client-secret"}'
            ),
        )

    monkeypatch.setattr(server, "urlopen", reject)

    with pytest.raises(server._OAuthExchangeError) as error_info:
        server._exchange_authorization_code(
            flow,
            "authorization-code",
            "compatibility-client-secret",
        )

    assert captured is not None
    assert captured.full_url == server.GOOGLE_TOKEN_ENDPOINT
    assert captured.get_method() == "POST"
    assert captured.get_header("Content-type") == "application/x-www-form-urlencoded"
    request_body = captured.data
    assert isinstance(request_body, bytes)
    assert b"{" not in request_body
    assert b"&" in request_body
    assert {field.partition(b"=")[0] for field in request_body.split(b"&")} == {
        b"client_id",
        b"client_secret",
        b"code",
        b"code_verifier",
        b"grant_type",
        b"redirect_uri",
    }
    request_fields = parse_qs(request_body.decode("ascii"))
    assert set(request_fields) == {
        "client_id",
        "client_secret",
        "code",
        "code_verifier",
        "grant_type",
        "redirect_uri",
    }
    assert request_fields["grant_type"] == ["authorization_code"]
    assert request_fields["redirect_uri"] == [flow.callback_url]
    assert error_info.value.safe_error_code == "TOKEN_EXCHANGE_INVALID_GRANT"
    assert (
        error_info.value.safe_error_description
        == "code=[REDACTED] verifier=[REDACTED] client_secret=[REDACTED]"
    )
    assert "authorization-code" not in str(error_info.value)
    assert "verifier-value" not in str(error_info.value)
    assert "compatibility-client-secret" not in str(error_info.value)


def test_callback_consumes_a_flow_before_token_exchange_to_block_code_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStore({}))
    server._control_call(state, method="google.oauth.start")
    flow = state.active_flow
    assert flow is not None
    exchanges = 0
    exchange_started = threading.Event()
    release_exchange = threading.Event()
    first_response_status: list[int] = []

    def exchange(
        bound_flow: server._OAuthFlow,
        code: str,
        client_secret: str | None,
    ) -> tuple[str, str, str | None]:
        nonlocal exchanges
        exchanges += 1
        assert bound_flow.callback_url == flow.callback_url
        assert code
        assert client_secret == "compatibility-client-secret"
        exchange_started.set()
        assert release_exchange.wait(timeout=2)
        return "refresh-value", "access-value", None

    monkeypatch.setattr(server, "_exchange_authorization_code", exchange)
    callback_url = (
        f"{flow.callback_url}?{urlencode({'state': flow.state, 'code': 'authorization-code'})}"
    )

    def first_callback() -> None:
        with urlopen(callback_url, timeout=2) as response:
            first_response_status.append(response.status)

    first_callback_thread = threading.Thread(target=first_callback)
    first_callback_thread.start()
    assert exchange_started.wait(timeout=2)
    with pytest.raises(HTTPError) as duplicate:
        urlopen(callback_url, timeout=2)
    release_exchange.set()
    first_callback_thread.join(timeout=2)

    assert duplicate.value.code == 400
    assert first_response_status == [200]
    assert not first_callback_thread.is_alive()
    assert exchanges == 1
    assert state.active_flow is None


def test_callback_exposes_only_redacted_token_exchange_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStore({}))
    server._control_call(state, method="google.oauth.start")
    flow = state.active_flow
    assert flow is not None

    def reject(
        bound_flow: server._OAuthFlow,
        code: str,
        client_secret: str | None,
    ) -> tuple[str, str]:
        del bound_flow, code, client_secret
        raise server._OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_GRANT",
            "Google rejected the authorization code or its PKCE/redirect binding.",
        )

    monkeypatch.setattr(server, "_exchange_authorization_code", reject)
    callback_url = (
        f"{flow.callback_url}?{urlencode({'state': flow.state, 'code': 'authorization-code'})}"
    )

    with pytest.raises(HTTPError) as failed:
        urlopen(callback_url)

    payload = server._control_call(state, method="google.connection.get")
    assert failed.value.code == 502
    assert payload["safe_error_code"] == "TOKEN_EXCHANGE_INVALID_GRANT"
    assert (
        payload["safe_error_description"]
        == "Google rejected the authorization code or its PKCE/redirect binding."
    )
    assert "authorization-code" not in repr(payload)
    assert flow.verifier not in repr(payload)


def test_refresh_grant_rotates_keyring_and_keeps_access_token_in_mcp_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemorySecretStore({"refresh": "stored-value"})
    state = _state(store)
    calls: list[tuple[str, str | None, str | None]] = []

    def refresh(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None, str | None]:
        calls.append((value, client_id, client_secret))
        return "access-value", server._now_ms() + 10_000, "rotated-value", None

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    state.ensure_access_token()

    assert len(calls) == 1
    assert calls[0][1] == "desktop-client"
    assert calls[0][2] == "compatibility-client-secret"
    assert state.access_token == "access-value"
    assert store.values["refresh"] == "rotated-value"
    assert "access-value" not in repr(state.connection_payload())
    assert "compatibility-client-secret" not in repr(state.connection_payload())


def test_ensure_access_token_self_heals_account_email_from_refresh_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access tokens (and any id_token that arrives with them) are process-
    memory-only, so a restarted MCP process must re-derive account_email on
    its next refresh rather than requiring the user to reconnect."""

    store = _MemorySecretStore({"refresh": "stored-value"})
    state = _state(store)
    assert state.account_email is None

    def refresh(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None, str | None]:
        del value, client_id, client_secret
        return "access-value", server._now_ms() + 10_000, None, "user@example.com"

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    state.ensure_access_token()

    assert state.account_email == "user@example.com"


def test_refresh_access_token_decodes_email_from_id_token(monkeypatch: pytest.MonkeyPatch) -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    body = json.dumps(
        {"access_token": "access-value", "expires_in": 3600, "id_token": token}
    ).encode("utf-8")
    monkeypatch.setattr(server, "urlopen", lambda request, *, timeout: _HTTPResponse(body))

    access_token, _, rotated_refresh_token, email = server._refresh_access_token(
        "stored-refresh-token", "desktop-client", "compatibility-client-secret"
    )

    assert access_token == "access-value"
    assert rotated_refresh_token is None
    assert email == "user@example.com"


def test_exchange_authorization_code_decodes_email_from_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = server._OAuthFlow(
        flow_id="flow-1",
        state="state-value",
        verifier="verifier-value",
        callback_url="http://127.0.0.1:43123/oauth/callback",
        expires_at_ms=server._now_ms() + 60_000,
        client_id="desktop-client",
    )
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    body = json.dumps(
        {"refresh_token": "refresh-value", "access_token": "access-value", "id_token": token}
    ).encode("utf-8")
    monkeypatch.setattr(server, "urlopen", lambda request, *, timeout: _HTTPResponse(body))

    refresh_token, access_token, email = server._exchange_authorization_code(
        flow, "authorization-code", "compatibility-client-secret"
    )

    assert refresh_token == "refresh-value"
    assert access_token == "access-value"
    assert email == "user@example.com"


def test_refresh_grant_uses_form_encoded_mcp_only_client_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Request | None = None

    def accept(request: Request, *, timeout: int) -> _HTTPResponse:
        nonlocal captured
        del timeout
        captured = request
        return _HTTPResponse(b'{"access_token":"access-value","expires_in":3600}')

    monkeypatch.setattr(server, "urlopen", accept)

    access_token, _, rotated_refresh_token, _ = server._refresh_access_token(
        "stored-refresh-token",
        "desktop-client",
        "compatibility-client-secret",
    )

    assert access_token == "access-value"
    assert rotated_refresh_token is None
    assert captured is not None
    assert captured.full_url == server.GOOGLE_TOKEN_ENDPOINT
    assert captured.get_method() == "POST"
    assert captured.get_header("Content-type") == "application/x-www-form-urlencoded"
    request_body = captured.data
    assert isinstance(request_body, bytes)
    assert b"{" not in request_body
    assert {field.partition(b"=")[0] for field in request_body.split(b"&")} == {
        b"client_id",
        b"client_secret",
        b"refresh_token",
        b"grant_type",
    }
    assert parse_qs(request_body.decode("ascii"))["grant_type"] == ["refresh_token"]


def test_missing_client_secret_blocks_oauth_before_any_authorization_flow() -> None:
    state = server._WorkspaceState(keyring=_MemorySecretStore({}))
    state.oauth_settings = GoogleOAuthSettings(google_oauth_client_id="desktop-client")

    with pytest.raises(server._OAuthConfigurationError) as error_info:
        server._control_call(state, method="google.oauth.start")

    assert error_info.value.safe_code == "GOOGLE_OAUTH_CLIENT_SECRET_MISSING"
    assert state.active_flow is None


def test_concurrent_expired_access_token_refreshes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _MemorySecretStore({"refresh": "stored-value"})
    state = _state(store)
    entered = threading.Barrier(4)
    calls = 0
    call_lock = threading.Lock()

    def refresh(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None, str | None]:
        nonlocal calls
        del value, client_id, client_secret
        with call_lock:
            calls += 1
        return "access-value", server._now_ms() + 10_000, None, None

    monkeypatch.setattr(server, "_refresh_access_token", refresh)

    def worker() -> None:
        entered.wait()
        state.ensure_access_token()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    entered.wait()
    for thread in threads:
        thread.join(timeout=2)
    assert calls == 1


def test_invalid_grant_requires_reauthentication(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(_MemorySecretStore({"refresh": "stored-value"}))

    def invalid(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None]:
        del value, client_id, client_secret
        raise server._OAuthReauthenticationRequired

    monkeypatch.setattr(server, "_refresh_access_token", invalid)
    assert server._control_call(state, method="google.connection.get")["reauth_required"] is True
    assert state.connection_state is CredentialState.REAUTH_REQUIRED


@pytest.mark.parametrize("revoke_result", (True, False))
def test_disconnect_always_cleans_local_credential_and_memory(
    monkeypatch: pytest.MonkeyPatch,
    revoke_result: bool,
) -> None:
    store = _MemorySecretStore({"refresh": "stored-value"})
    state = _state(store)
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    state.connection_state = CredentialState.CONNECTED
    monkeypatch.setattr(server, "_revoke_refresh_token", lambda _value: revoke_result)

    payload = server._control_call(state, method="google.connection.disconnect")

    assert payload["revoke_attempted"] is True
    assert payload["revoke_succeeded"] is revoke_result
    assert payload["credential_deleted"] is True
    assert state.access_token is None
    assert state.connection_state is CredentialState.NOT_CONNECTED
    assert store.values == {}


def _state(store: _MemorySecretStore) -> server._WorkspaceState:
    state = server._WorkspaceState(keyring=store)
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    return state


class _MemorySecretStore:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        del service, account
        self.values["refresh"] = secret

    def get_secret(self, *, service: str, account: str) -> str | None:
        del service, account
        return self.values.get("refresh")

    def delete_secret(self, *, service: str, account: str) -> bool:
        del service, account
        return self.values.pop("refresh", None) is not None


class _HTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _HTTPResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body
