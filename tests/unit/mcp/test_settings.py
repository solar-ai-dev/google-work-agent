from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    credential_provider as settings,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GoogleOAuthSettings,
)


def test_google_credential__provider_load_from__local_env_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    another_directory = tmp_path / "another-directory"
    another_directory.mkdir()
    monkeypatch.chdir(another_directory)
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.local").write_text(
        "GOOGLE_OAUTH_CLIENT_ID=dev-desktop-client-id\n"
        "GOOGLE_OAUTH_CLIENT_SECRET=compatibility-client-secret\n",
        encoding="utf-8",
    )

    credential_provider = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={},
    )

    assert credential_provider.google_oauth_client_id == "dev-desktop-client-id"
    assert not hasattr(credential_provider, "google_oauth_client_secret")
    assert "dev-desktop-client-id" not in repr(credential_provider)
    assert "compatibility-client-secret" not in repr(credential_provider)


def test_process_environment__overrides_local__env_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.local").write_text(
        "GOOGLE_OAUTH_CLIENT_ID=file-client-id\nGOOGLE_OAUTH_CLIENT_SECRET=file-client-secret\n",
        encoding="utf-8",
    )

    credential_provider = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={
            "GOOGLE_OAUTH_CLIENT_ID": "environment-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "environment-client-secret",
        },
    )

    assert credential_provider.google_oauth_client_id == "environment-client-id"
    assert not hasattr(credential_provider, "google_oauth_client_secret")


def test_google_oauth_client__id_is_optional_at__import_and_load_time(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)

    credential_provider = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={},
    )

    assert credential_provider.google_oauth_client_id is None
    assert not hasattr(credential_provider, "google_oauth_client_secret")


def test_whitespace_google__oauth_client_id__is_not_configured() -> None:
    credential_provider = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={"GOOGLE_OAUTH_CLIENT_ID": "  \t  "},
    )

    assert credential_provider.google_oauth_client_id is None


def test_production_does__not_load__local_env_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.local").write_text(
        "GOOGLE_OAUTH_CLIENT_ID=dev-desktop-client-id\n"
        "GOOGLE_OAUTH_CLIENT_SECRET=compatibility-client-secret\n",
        encoding="utf-8",
    )

    credential_provider = GoogleOAuthSettings.load(runtime_environment="PRODUCTION", environment={})

    assert credential_provider.google_oauth_client_id is None
    assert not hasattr(credential_provider, "google_oauth_client_secret")


def test_desktop_oauth__secret_environment__value_is_ignored() -> None:
    credential_provider = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={
            "GOOGLE_OAUTH_CLIENT_ID": "desktop-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "  \t  ",
        },
    )

    assert credential_provider.google_oauth_client_id == "desktop-client-id"
    assert not hasattr(credential_provider, "google_oauth_client_secret")
