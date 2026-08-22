from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, build_opener

from google_work_agent.adapters.connectors.google.mcp.workspace_tools import _control_call, _WorkspaceState
from google_work_agent.adapters.connectors.google.mcp.oauth_settings import GoogleOAuthSettings


def test_mcp_oauth_flow_uses_google_loopback_authorization_and_no_token_leakage() -> None:
    state = _WorkspaceState(keyring=_FakeSecretStore())
    state.oauth_settings = GoogleOAuthSettings(
        google_oauth_client_id="test-desktop-client-id",
        google_oauth_client_secret="compatibility-client-secret",
    )
    started = _control_call(state, method="google.oauth.start")
    callback_url = str(started["callback_url"])
    authorization_url = str(started["authorization_url"])
    assert callback_url.startswith("http://127.0.0.1:")
    assert "test-desktop-client-id" not in authorization_url
    state_value = parse_qs(urlparse(authorization_url).query)["state"][0]
    response = build_opener(_NoRedirect()).open(f"{authorization_url}&state={state_value}")
    assert response.code == 302
    parsed = urlparse(response.headers["Location"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [callback_url]
    assert query["scope"] == [
        " ".join(
            [
                "openid",
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/tasks",
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
                "https://www.googleapis.com/auth/calendar.events.freebusy",
            ]
        )
    ]


class _FakeSecretStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        self.values[(service, account)] = secret

    def get_secret(self, *, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete_secret(self, *, service: str, account: str) -> bool:
        return self.values.pop((service, account), None) is not None


class _NoRedirect(HTTPRedirectHandler):
    def http_error_302(
        self,
        request: object,
        fp: object,
        code: int,
        message: str,
        headers: object,
    ) -> object:
        del request, fp, message
        return type("Response", (), {"code": code, "headers": headers})()
