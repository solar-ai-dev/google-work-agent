from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from google_work_agent.mcp import settings
from google_work_agent.mcp.settings import GoogleOAuthSettings


def test_google_oauth_settings_load_from_local_env_file(
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

    oauth_settings = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={},
    )

    assert oauth_settings.google_oauth_client_id == "dev-desktop-client-id"
    assert oauth_settings.google_oauth_client_secret == "compatibility-client-secret"
    assert "dev-desktop-client-id" not in repr(oauth_settings)
    assert "compatibility-client-secret" not in repr(oauth_settings)


def test_process_environment_overrides_local_env_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.local").write_text(
        "GOOGLE_OAUTH_CLIENT_ID=file-client-id\nGOOGLE_OAUTH_CLIENT_SECRET=file-client-secret\n",
        encoding="utf-8",
    )

    oauth_settings = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={
            "GOOGLE_OAUTH_CLIENT_ID": "environment-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "environment-client-secret",
        },
    )

    assert oauth_settings.google_oauth_client_id == "environment-client-id"
    assert oauth_settings.google_oauth_client_secret == "environment-client-secret"


def test_google_oauth_client_id_is_optional_at_import_and_load_time(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)

    oauth_settings = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={},
    )

    assert oauth_settings.google_oauth_client_id is None
    assert oauth_settings.google_oauth_client_secret is None


def test_whitespace_google_oauth_client_id_is_not_configured() -> None:
    oauth_settings = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={"GOOGLE_OAUTH_CLIENT_ID": "  \t  "},
    )

    assert oauth_settings.google_oauth_client_id is None


def test_production_does_not_load_local_env_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env.local").write_text(
        "GOOGLE_OAUTH_CLIENT_ID=dev-desktop-client-id\n"
        "GOOGLE_OAUTH_CLIENT_SECRET=compatibility-client-secret\n",
        encoding="utf-8",
    )

    oauth_settings = GoogleOAuthSettings.load(runtime_environment="PRODUCTION", environment={})

    assert oauth_settings.google_oauth_client_id is None
    assert oauth_settings.google_oauth_client_secret is None


def test_whitespace_google_oauth_client_secret_is_not_configured() -> None:
    oauth_settings = GoogleOAuthSettings.load(
        runtime_environment="DEVELOPMENT",
        environment={
            "GOOGLE_OAUTH_CLIENT_ID": "desktop-client-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "  \t  ",
        },
    )

    assert oauth_settings.google_oauth_client_secret is None
