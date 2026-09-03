from __future__ import annotations

import json
import threading
from email.message import Message
from http.client import HTTPConnection
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import pytest

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as server,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleOAuthSettings,
)

CredentialState = server.CredentialState


def _fake_id_token(claims: dict[str, object]) -> str:
    header = server._b64url_encode(b'{"alg":"RS256","typ":"JWT"}')
    payload = server._b64url_encode(json.dumps(claims).encode("utf-8"))
    return f"{header}.{payload}.unverified-signature"


def test_pkce_s256__matches_rfc__rfc_7636_vector() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert server._pkce_s256(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_required_scopes__include_openid__and_email() -> None:
    assert "openid" in server.REQUIRED_SCOPES
    assert "https://www.googleapis.com/auth/userinfo.email" in server.REQUIRED_SCOPES


def test_verified_email__from_id_token__extracts_verified_email() -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    assert server._verified_email_from_id_token(token) == "user@example.com"


def test_verified_email__from_id_token__rejects_unverified_email() -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": False})
    assert server._verified_email_from_id_token(token) is None


def test_verified_email_from__id_token_rejects__missing_email_verified_claim() -> None:
    token = _fake_id_token({"email": "user@example.com"})
    assert server._verified_email_from_id_token(token) is None


def test_verified_email__from_id_token__rejects_malformed_token() -> None:
    assert server._verified_email_from_id_token("not-a-jwt") is None
    assert server._verified_email_from_id_token("a.b") is None
    assert server._verified_email_from_id_token("a.!!!not-base64!!!.c") is None


def test_authorization_code_grant_binds__the_callback_uri_and__reports_only_redacted_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = server._OAuthFlow(
        flow_id="flow-1",
        state="state-value",
        verifier="verifier-value",
        callback_url="http://127.0.0.1:43123/oauth/callback",
        expires_at_ms=server._now_ms() + 60_000,
        client_id="desktop-client",
        operation_ref="operation-1",
        client_secret="compatibility-client-secret",
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
        b"code",
        b"code_verifier",
        b"grant_type",
        b"redirect_uri",
        b"client_secret",
    }
    request_fields = parse_qs(request_body.decode("ascii"))
    assert set(request_fields) == {
        "client_id",
        "code",
        "code_verifier",
        "grant_type",
        "redirect_uri",
        "client_secret",
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


def test_callback_consumes_a__flow_before_token_exchange__to_block_code_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({}))
    server._control_call(
        state, method="google.oauth.start", arguments={"operation_ref": "operation-1"}
    )
    flow = state.active_flow
    assert flow is not None
    exchanges = 0
    exchange_started = threading.Event()
    release_exchange = threading.Event()
    first_response_status: list[int] = []

    def exchange(
        bound_flow: server._OAuthFlow,
        code: str,
    ) -> tuple[str, str, str | None]:
        nonlocal exchanges
        exchanges += 1
        assert bound_flow.callback_url == flow.callback_url
        assert code
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


def test_callback_exposes__only_redacted__token_exchange_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({}))
    server._control_call(
        state, method="google.oauth.start", arguments={"operation_ref": "operation-1"}
    )
    flow = state.active_flow
    assert flow is not None

    def reject(
        bound_flow: server._OAuthFlow,
        code: str,
    ) -> tuple[str, str]:
        del bound_flow, code
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


def test_refresh_grant_rotates__keyring_and_keeps_access__token_in_mcp_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemorySecretStorePort({"refresh": "stored-value"})
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


def test_ensure_access_token__self_heals_account_email__from_refresh_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Access tokens (and any id_token that arrives with them) are process-
    memory-only, so a restarted MCP process must re-derive account_email on
    its next refresh rather than requiring the user to reconnect."""

    store = _MemorySecretStorePort({"refresh": "stored-value"})
    state = _state(store)
    assert state.account_email is None

    def refresh(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None, str | None]:
        del value, client_id, client_secret
        return "access-value", server._now_ms() + 10_000, None, "user@example.com"

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(
            email="user@example.com",
            http_status=200,
            account_id="google-subject",
        ),
    )
    state.ensure_access_token()

    assert state.account_email == "user@example.com"
    assert state.account_id == "google-subject"


def test_ensure_access_token__resolves_verified_email__from_userinfo_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))

    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: ("access-value", server._now_ms() + 10_000, None, None),
    )
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda access_token: server._UserInfoIdentityResolution(
            email="user@example.com" if access_token == "access-value" else None,
            http_status=200,
            account_id="google-subject" if access_token == "access-value" else None,
        ),
    )

    state.ensure_access_token()

    assert state.connection_state is CredentialState.CONNECTED
    assert state.account_email == "user@example.com"
    assert state.account_id == "google-subject"


def test_valid_access_token__with_resolved_identity__skips_refresh_and_userinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.account_id = "google-subject"
    state.account_email = "user@example.com"
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: ("access-value", server._now_ms() + 10_000, None, None),
    )
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: pytest.fail("UserInfo must not run for a known identity"),
    )

    state.ensure_access_token()

    assert state.account_email == "user@example.com"


def test_valid_access__token_resolves_missing__identity_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    refresh_calls = 0
    userinfo_calls = 0

    def refresh(*_args: object) -> tuple[str, int, str | None, str | None]:
        nonlocal refresh_calls
        refresh_calls += 1
        return "unexpected", server._now_ms() + 10_000, None, None

    def resolve(access_token: str) -> server._UserInfoIdentityResolution:
        nonlocal userinfo_calls
        userinfo_calls += 1
        assert access_token == "access-value"
        return server._UserInfoIdentityResolution(email="user@example.com", http_status=200)

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(server, "_resolve_account_identity_from_userinfo", resolve)

    state.ensure_access_token()

    assert refresh_calls == 0
    assert userinfo_calls == 1
    assert state.account_email == "user@example.com"


def test_valid_access_token__with_unverified_userinfo__keeps_oauth_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    refresh_calls = 0

    def refresh(*_args: object) -> tuple[str, int, str | None, str | None]:
        nonlocal refresh_calls
        refresh_calls += 1
        return "unexpected", server._now_ms() + 10_000, None, None

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(
            email=server._verified_email_from_userinfo_payload(
                {"sub": "google-subject", "email": "user@example.com", "email_verified": False}
            ),
            http_status=200,
        ),
    )

    state.ensure_access_token()

    assert refresh_calls == 0
    assert state.connection_state is CredentialState.CONNECTED
    assert state.account_email is None


def test_valid_access__token_userinfo_failure__keeps_oauth_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: pytest.fail("valid token must not refresh"),
    )
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(email=None, http_status=None),
    )

    state.ensure_access_token()

    assert state.connection_state is CredentialState.CONNECTED
    assert state.account_email is None


def test_valid_token_userinfo__http_401_refreshes_once__and_retries_userinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "old-access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    refresh_calls = 0
    userinfo_calls = 0

    def refresh(*_args: object) -> tuple[str, int, str | None, str | None]:
        nonlocal refresh_calls
        refresh_calls += 1
        return "new-access-value", server._now_ms() + 10_000, None, None

    def resolve(access_token: str) -> server._UserInfoIdentityResolution:
        nonlocal userinfo_calls
        userinfo_calls += 1
        return server._UserInfoIdentityResolution(
            email=None if access_token == "old-access-value" else "user@example.com",
            http_status=401 if access_token == "old-access-value" else 200,
        )

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(server, "_resolve_account_identity_from_userinfo", resolve)

    state.ensure_access_token()

    assert refresh_calls == 1
    assert userinfo_calls == 2
    assert state.access_token == "new-access-value"
    assert state.account_email == "user@example.com"


def test_userinfo_401__refresh_id_token__email_skips_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "old-access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    userinfo_calls = 0

    def resolve(_access_token: str) -> server._UserInfoIdentityResolution:
        nonlocal userinfo_calls
        userinfo_calls += 1
        return (
            server._UserInfoIdentityResolution(email=None, http_status=401)
            if userinfo_calls == 1
            else server._UserInfoIdentityResolution(
                email="user@example.com",
                http_status=200,
                account_id="google-subject",
            )
        )

    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: ("new-access-value", server._now_ms() + 10_000, None, "user@example.com"),
    )
    monkeypatch.setattr(server, "_resolve_account_identity_from_userinfo", resolve)

    state.ensure_access_token()

    assert userinfo_calls == 2
    assert state.account_email == "user@example.com"
    assert state.account_id == "google-subject"


def test_userinfo_401__refresh_failure__requires_reauthentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "old-access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(email=None, http_status=401),
    )
    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: (_ for _ in ()).throw(server._OAuthReauthenticationRequired()),
    )

    payload = server._control_call(state, method="google.connection.get")

    assert payload["reauth_required"] is True
    assert state.account_email is None


def test_userinfo_401__retry_401_does__not_refresh_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "old-access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    refresh_calls = 0
    userinfo_calls = 0

    def refresh(*_args: object) -> tuple[str, int, str | None, str | None]:
        nonlocal refresh_calls
        refresh_calls += 1
        return "new-access-value", server._now_ms() + 10_000, None, None

    def resolve(_access_token: str) -> server._UserInfoIdentityResolution:
        nonlocal userinfo_calls
        userinfo_calls += 1
        return server._UserInfoIdentityResolution(email=None, http_status=401)

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(
            email="user@example.com",
            http_status=200,
            account_id="google-subject",
        ),
    )
    monkeypatch.setattr(server, "_resolve_account_identity_from_userinfo", resolve)

    state.ensure_access_token()

    assert refresh_calls == 1
    assert userinfo_calls == 2
    assert state.connection_state is CredentialState.REAUTH_REQUIRED
    assert state.account_email is None


@pytest.mark.parametrize(
    "resolution",
    (
        server._UserInfoIdentityResolution(email=None, http_status=403),
        server._UserInfoIdentityResolution(email=None, http_status=200),
    ),
)
def test_non_401__userinfo_failure__does_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
    resolution: server._UserInfoIdentityResolution,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    state.access_token = "access-value"
    state.access_token_expires_at_ms = server._now_ms() + 10_000
    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: pytest.fail("non-401 UserInfo failure must not refresh"),
    )
    monkeypatch.setattr(
        server, "_resolve_account_identity_from_userinfo", lambda _access_token: resolution
    )

    state.ensure_access_token()

    assert state.connection_state is CredentialState.CONNECTED
    assert state.account_email is None


def test_userinfo_requires__sub_and__verified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: Request | None = None

    def userinfo(request: Request, *, timeout: int) -> _HTTPResponse:
        nonlocal captured
        assert timeout == 10
        captured = request
        return _HTTPResponse(
            b'{"sub":"google-subject","email":"user@example.com","email_verified":true}'
        )

    monkeypatch.setattr(server, "urlopen", userinfo)

    identity = server._resolve_account_identity_from_userinfo("access-value")
    assert identity.email == "user@example.com"
    assert identity.account_id == "google-subject"
    assert captured is not None
    assert captured.full_url == server.GOOGLE_USERINFO_ENDPOINT
    assert captured.get_method() == "GET"
    assert captured.get_header("Authorization") == "Bearer access-value"
    assert (
        server._verified_email_from_userinfo_payload(
            {"sub": "google-subject", "email": "user@example.com", "email_verified": False}
        )
        is None
    )
    assert (
        server._verified_email_from_userinfo_payload(
            {"email": "user@example.com", "email_verified": True}
        )
        is None
    )


def test_expired_access__token_userinfo_failure__keeps_oauth_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))
    monkeypatch.setattr(
        server,
        "_refresh_access_token",
        lambda *_args: ("access-value", server._now_ms() + 10_000, None, None),
    )
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(email=None, http_status=None),
    )

    state.ensure_access_token()

    assert state.connection_state is CredentialState.CONNECTED
    assert state.account_email is None


def test_refresh_access__token_decodes_email__from_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    body = json.dumps(
        {"access_token": "access-value", "expires_in": 3600, "id_token": token}
    ).encode("utf-8")
    monkeypatch.setattr(server, "urlopen", lambda request, *, timeout: _HTTPResponse(body))

    access_token, _, rotated_refresh_token, email = server._refresh_access_token(
        "stored-refresh-token", "desktop-client"
    )

    assert access_token == "access-value"
    assert rotated_refresh_token is None
    assert email == "user@example.com"


def test_exchange_authorization__code_decodes_email__from_id_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = server._OAuthFlow(
        flow_id="flow-1",
        state="state-value",
        verifier="verifier-value",
        callback_url="http://127.0.0.1:43123/oauth/callback",
        expires_at_ms=server._now_ms() + 60_000,
        client_id="desktop-client",
        operation_ref="operation-1",
    )
    token = _fake_id_token({"email": "user@example.com", "email_verified": True})
    body = json.dumps(
        {"refresh_token": "refresh-value", "access_token": "access-value", "id_token": token}
    ).encode("utf-8")
    monkeypatch.setattr(server, "urlopen", lambda request, *, timeout: _HTTPResponse(body))

    refresh_token, access_token, email = server._exchange_authorization_code(
        flow, "authorization-code"
    )

    assert refresh_token == "refresh-value"
    assert access_token == "access-value"
    assert email == "user@example.com"


def test_refresh_grant_uses__form_encoded_mcp__only_client_credentials(
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
        b"refresh_token",
        b"grant_type",
        b"client_secret",
    }
    request_fields = parse_qs(request_body.decode("ascii"))
    assert request_fields["grant_type"] == ["refresh_token"]
    assert request_fields["client_secret"] == ["compatibility-client-secret"]


def test_desktop_oauth__starts_with_public__client_id_only() -> None:
    state = server.GoogleWorkspaceCredentialProvider(keyring=_MemorySecretStorePort({}))
    state.oauth_settings = GoogleOAuthSettings(google_oauth_client_id="desktop-client")

    result = server._control_call(
        state, method="google.oauth.start", arguments={"operation_ref": "operation-1"}
    )
    assert result["flow_id"]
    assert state.active_flow is not None
    assert urlparse(state.active_flow.callback_url).path == ""


def test_unrelated_loopback_request__does_not_expire__active_oauth_flow() -> None:
    state = server.GoogleWorkspaceCredentialProvider(keyring=_MemorySecretStorePort({}))
    state.oauth_settings = GoogleOAuthSettings(google_oauth_client_id="desktop-client")
    server._control_call(
        state, method="google.oauth.start", arguments={"operation_ref": "operation-1"}
    )
    flow = state.active_flow
    assert flow is not None
    parsed_callback = urlparse(flow.callback_url)
    assert parsed_callback.hostname is not None
    assert parsed_callback.port is not None

    unrelated = HTTPConnection(parsed_callback.hostname, parsed_callback.port, timeout=2)
    try:
        unrelated.request("GET", "/favicon.ico")
        response = unrelated.getresponse()
        assert response.status == 404
        response.read()
    finally:
        unrelated.close()

    assert state.active_flow is flow

    invalid_callback = HTTPConnection(parsed_callback.hostname, parsed_callback.port, timeout=2)
    try:
        invalid_callback.request("GET", "/?state=invalid")
        response = invalid_callback.getresponse()
        assert response.status == 400
        response.read()
    finally:
        invalid_callback.close()


def test_successful_callback__with_validated_loopback_return__redirects_browser_to_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(_MemorySecretStorePort({}))
    server._control_call(
        state, method="google.oauth.start", arguments={"operation_ref": "operation-1"}
    )
    flow = state.active_flow
    assert flow is not None
    parsed_callback = urlparse(flow.callback_url)
    assert parsed_callback.hostname is not None
    assert parsed_callback.port is not None
    return_url = "http://127.0.0.1:18775/"

    authorize = HTTPConnection(parsed_callback.hostname, parsed_callback.port, timeout=2)
    try:
        authorize.request(
            "GET",
            f"/oauth/authorize?{urlencode({'state': flow.state, 'return_to': return_url})}",
        )
        response = authorize.getresponse()
        assert response.status == 302
        assert response.getheader("Location", "").startswith(
            server.GOOGLE_AUTHORIZATION_ENDPOINT
        )
        response.read()
    finally:
        authorize.close()

    active_flow = state.active_flow
    assert active_flow is not None
    assert active_flow.return_url == return_url
    monkeypatch.setattr(
        server,
        "_exchange_authorization_code",
        lambda _flow, _code: ("refresh-value", "access-value", "user@example.com"),
    )

    callback = HTTPConnection(parsed_callback.hostname, parsed_callback.port, timeout=2)
    try:
        callback.request(
            "GET",
            f"/?{urlencode({'state': flow.state, 'code': 'authorization-code'})}",
        )
        response = callback.getresponse()
        assert response.status == 303
        assert response.getheader("Location") == return_url
        assert response.getheader("Cache-Control") == "no-store"
        assert response.read() == b""
    finally:
        callback.close()

    assert state.connection_state is CredentialState.CONNECTED
    assert state.active_flow is None


@pytest.mark.parametrize(
    "return_url",
    (
        "https://127.0.0.1:18775/",
        "http://localhost:18775/",
        "http://127.0.0.1/",
        "http://user@127.0.0.1:18775/",
        "http://127.0.0.1:18775/app",
        "http://127.0.0.1:18775/?source=oauth",
        "http://127.0.0.1:18775/#connected",
    ),
)
def test_oauth_return_url__with_noncanonical_target__is_rejected(return_url: str) -> None:
    assert server._validated_oauth_return_url(return_url) is None


def test_concurrent_expired__access_token__refreshes_once(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _MemorySecretStorePort({"refresh": "stored-value"})
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
        return "access-value", server._now_ms() + 10_000, None, "user@example.com"

    monkeypatch.setattr(server, "_refresh_access_token", refresh)
    monkeypatch.setattr(
        server,
        "_resolve_account_identity_from_userinfo",
        lambda _access_token: server._UserInfoIdentityResolution(
            email="user@example.com",
            http_status=200,
            account_id="google-subject",
        ),
    )

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


def test_invalid_grant__requires__reauthentication(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(_MemorySecretStorePort({"refresh": "stored-value"}))

    def invalid(
        value: str, client_id: str | None, client_secret: str | None
    ) -> tuple[str, int, str | None]:
        del value, client_id, client_secret
        raise server._OAuthReauthenticationRequired

    monkeypatch.setattr(server, "_refresh_access_token", invalid)
    assert server._control_call(state, method="google.connection.get")["reauth_required"] is True
    assert state.connection_state is CredentialState.REAUTH_REQUIRED


@pytest.mark.parametrize("revoke_result", (True, False))
def test_disconnect_always__cleans_local__credential_and_memory(
    monkeypatch: pytest.MonkeyPatch,
    revoke_result: bool,
) -> None:
    store = _MemorySecretStorePort({"refresh": "stored-value"})
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


def _state(store: _MemorySecretStorePort) -> server.GoogleWorkspaceCredentialProvider:
    state = server.GoogleWorkspaceCredentialProvider(keyring=store)
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="desktop-client",
        google_oauth_client_secret="compatibility-client-secret",
    )
    return state


class _MemorySecretStorePort:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def put(self, key: str, secret_bytes: bytes) -> None:
        del key
        self.values["refresh"] = secret_bytes.decode("utf-8")

    def get(self, key: str) -> bytes | None:
        del key
        value = self.values.get("refresh")
        return None if value is None else value.encode("utf-8")

    def delete(self, key: str) -> None:
        del key
        self.values.pop("refresh", None)


class _HTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _HTTPResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body
