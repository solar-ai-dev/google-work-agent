from pathlib import Path

import pytest
from scripts import seed_google_e2e as seed


def test_task_fixture_preserves_notes_and_planned_date() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure4", "task-upload", "--title", "보고서",
        "--notes", "자료 정리", "--scheduled-date", "2026-09-07",
    ])
    _, payload = seed.build_fixture(args)
    assert args.execute is False
    assert payload == {
        "title": "[GWA E2E closure4] 보고서", "notes": "자료 정리",
        "due": "2026-09-07T00:00:00Z",
    }


def test_calendar_fixture_rejects_timezone_less_input() -> None:
    args = seed.parser().parse_args([
        "--tag", "closure4", "calendar-upload", "--title", "회의",
        "--start", "2026-09-08T14:00:00", "--end", "2026-09-08T14:30:00",
    ])
    with pytest.raises(ValueError, match="UTC offset"):
        seed.build_fixture(args)


def test_mail_fixture_rejects_other_recipients() -> None:
    with pytest.raises(SystemExit):
        seed.parser().parse_args([
            "--tag", "closure4", "mail-send", "--to", "other@example.com",
            "--subject", "회의", "--body", "내용",
        ])


@pytest.mark.parametrize("uncertain", [False, True])
def test_fixture_does_not_repeat_completed_or_uncertain_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uncertain: bool,
) -> None:
    from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
        credential_provider,
    )

    class Credential:
        account_email = seed.TEST_ACCOUNTS[0]

        def ensure_access_token(self) -> None:
            pass

    calls = []

    def write(*args: object, **kwargs: object) -> dict[str, str]:
        calls.append((args, kwargs))
        if uncertain:
            raise TimeoutError()
        return {"id": "created-1"}

    monkeypatch.setattr(seed, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(credential_provider, "GoogleWorkspaceCredentialProvider", Credential)
    monkeypatch.setattr(credential_provider, "_google_api_call", write)
    url, payload = seed.build_fixture(seed.parser().parse_args([
        "--tag", "closure4", "task-upload", "--title", "보고서",
    ]))
    if uncertain:
        with pytest.raises(TimeoutError):
            seed.execute_fixture(url, payload)
    else:
        assert seed.execute_fixture(url, payload)["id"] == "created-1"
    with pytest.raises(ValueError, match="재전송하지 않습니다"):
        seed.execute_fixture(url, payload)
    assert len(calls) == 1
