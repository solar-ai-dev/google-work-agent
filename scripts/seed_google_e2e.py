"""Development-only Google fixture preparation, never Product E2E evidence.

Run with PYTHONPATH=src and .venv-gpu. Commands preview by default; --execute
uses the existing DEVELOPMENT Google login. No production approval/claim is
fabricated. This explicit fixture writer is not imported by the application.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sqlite3
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

TEST_ACCOUNTS = ("bonggyulim0728@gmail.com", "qhdrbdhkdwks2@gmail.com")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--execute", action="store_true", help="실제 테스트 데이터 생성")
    result.add_argument("--tag", required=True, help="예: closure4-20260905")
    commands = result.add_subparsers(dest="command", required=True)
    task = commands.add_parser("task-upload", help="기본 목록에 테스트 태스크 생성")
    task.add_argument("--title", required=True)
    task.add_argument("--notes", default="제품 E2E 준비용 테스트 자료입니다.")
    task.add_argument("--scheduled-date", type=date.fromisoformat)
    calendar = commands.add_parser("calendar-upload", help="기본 캘린더에 테스트 일정 생성")
    calendar.add_argument("--title", required=True)
    calendar.add_argument("--description", default="제품 E2E 준비용 테스트 자료입니다.")
    calendar.add_argument("--start", type=datetime.fromisoformat, required=True)
    calendar.add_argument("--end", type=datetime.fromisoformat, required=True)
    calendar.add_argument("--attendee", choices=TEST_ACCOUNTS, action="append", default=[])
    mail = commands.add_parser("mail-send", help="지정한 테스트 계정에 메일 발송")
    mail.add_argument("--to", choices=TEST_ACCOUNTS, required=True)
    mail.add_argument("--subject", required=True)
    mail.add_argument("--body", required=True)
    return result


def build_fixture(arguments: argparse.Namespace) -> tuple[str, dict[str, Any]]:
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", arguments.tag):
        raise ValueError("tag는 영문, 숫자, 하이픈 1~64자로 입력하세요.")
    prefix = f"[GWA E2E {arguments.tag}] "
    if arguments.command == "task-upload":
        payload = {"title": prefix + arguments.title, "notes": arguments.notes}
        if arguments.scheduled_date is not None:
            payload["due"] = f"{arguments.scheduled_date.isoformat()}T00:00:00Z"
        return "https://tasks.googleapis.com/tasks/v1/lists/@default/tasks", payload
    if arguments.command == "calendar-upload":
        if (
            arguments.start.tzinfo is None or arguments.end.tzinfo is None
            or arguments.end <= arguments.start
        ):
            raise ValueError("일정은 UTC offset이 있는 시작/종료 시각과 양수 기간이 필요합니다.")
        return "https://www.googleapis.com/calendar/v3/calendars/primary/events", {
            "summary": prefix + arguments.title,
            "description": arguments.description,
            "start": {"dateTime": arguments.start.isoformat()},
            "end": {"dateTime": arguments.end.isoformat()},
            "attendees": [{"email": email} for email in sorted(set(arguments.attendee))],
        }
    if arguments.to not in TEST_ACCOUNTS:
        raise ValueError("메일 수신자는 지정된 테스트 계정만 허용합니다.")
    return "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
        "to": arguments.to, "subject": prefix + arguments.subject, "body": arguments.body,
    }


def execute_fixture(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    # Reuse credential refresh and redacted HTTP failures, not the production Write
    # tool dispatch: fixture setup has explicit CLI authorization, no fake claims.
    from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
        credential_provider,
    )

    os.environ["GOOGLE_OAUTH_ENV"] = "DEVELOPMENT"
    state = credential_provider.GoogleWorkspaceCredentialProvider()
    state.ensure_access_token()
    if state.account_email not in TEST_ACCOUNTS:
        raise ValueError("연결된 Google 계정이 허용된 테스트 계정이 아닙니다.")
    identity = json.dumps([state.account_email, url, payload], sort_keys=True, ensure_ascii=False)
    fingerprint = hashlib.sha256(identity.encode()).hexdigest()
    receipt_path = PROJECT_ROOT / ".runtime" / "e2e-fixtures.sqlite3"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(receipt_path) as receipts:
        receipts.execute(
            "CREATE TABLE IF NOT EXISTS fixture_attempts "
            "(fingerprint TEXT PRIMARY KEY, status TEXT NOT NULL, result_json TEXT)"
        )
        previous = receipts.execute(
            "SELECT status, result_json FROM fixture_attempts WHERE fingerprint=?", (fingerprint,)
        ).fetchone()
        if previous is not None:
            raise ValueError(
                f"동일 자료의 실행 기록이 있습니다({previous[0]}). 재전송하지 않습니다. "
                "Google에서 기존 결과를 먼저 확인하세요."
            )
        receipts.execute(
            "INSERT INTO fixture_attempts VALUES (?, 'STARTED', NULL)", (fingerprint,)
        )
        receipts.commit()
        body = payload
        if url.endswith("/messages/send"):
            message = EmailMessage()
            message["From"] = state.account_email
            message["To"] = payload["to"]
            message["Subject"] = payload["subject"]
            message["Message-ID"] = f"<gwa-e2e-{fingerprint}@example.invalid>"
            message.set_content(payload["body"])
            body = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        # No automatic resend on timeout or uncertain delivery.
        created = credential_provider._google_api_call(state, "POST", url, body=body)
        resource_id = created.get("id")
        if not isinstance(resource_id, str):
            raise ValueError("Google 생성 응답에 ID가 없습니다. 재전송하지 마세요.")
        result = {
            "fixture_only": True, "account": state.account_email,
            "id": resource_id, "thread_id": created.get("threadId"),
            "title": payload.get("title", payload.get("summary", payload.get("subject"))),
            "recipient": payload.get("to"), "status": "PROVIDER_CREATED",
        }
        receipts.execute(
            "UPDATE fixture_attempts SET status='PROVIDER_CREATED', result_json=? "
            "WHERE fingerprint=?", (json.dumps(result, ensure_ascii=False), fingerprint),
        )
        receipts.commit()
        return result


def main() -> None:
    arguments = parser().parse_args()
    try:
        url, payload = build_fixture(arguments)
        result = execute_fixture(url, payload) if arguments.execute else {
            "dry_run": True, "fixture_only": True, "endpoint": url, "payload": payload,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        # No credential, token, request body, or raw HTTP error is logged.
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        raise SystemExit(f"테스트 자료 준비 실패: {detail}. 자동 재전송하지 않았습니다.") from None


if __name__ == "__main__":
    main()
