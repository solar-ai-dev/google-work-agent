"""Project selected Gmail security-login facts without generative reinterpretation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)

_DEVICE_PATTERNS = (
    re.compile(r"([A-Za-z][A-Za-z0-9 ._-]{0,30})에서 새로 로그인함"),
    re.compile(r"([A-Za-z][A-Za-z0-9 ._-]{0,30}) 기기에서"),
)
_DATE_HEADER = re.compile(r"\bDate:\s*(.+?)(?=\s+Subject:|$)", re.IGNORECASE)


class GmailSecurityReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_gmail_security_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> GmailSecurityReadAnswerProjection | None:
    """Return device and message date for an exact selected login alert."""

    if not _supports_request(user_request, request_intent):
        return None
    evidence_item = next(
        (
            item
            for item in evidence
            if isinstance(item.get("excerpt"), str) and "새로 로그인" in str(item["excerpt"])
        ),
        None,
    )
    if evidence_item is None:
        return None
    excerpt = str(evidence_item["excerpt"])
    device = _device(excerpt)
    message_date = _message_date(excerpt)
    evidence_ref = _evidence_ref(evidence_item)
    if device is None or message_date is None or evidence_ref is None:
        return None
    parsed_date, timezone_label = message_date

    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    if korean:
        date_text = (
            f"{parsed_date.year}년 {parsed_date.month}월 {parsed_date.day}일 "
            f"{parsed_date:%H:%M:%S} {timezone_label}"
        )
        answer = (
            f"선택한 메일에서 확인된 로그인 기기는 {device}이며, "
            f"알림 날짜는 {date_text}입니다."
        )
        section = "선택한 Gmail 보안 알림의 로그인 기기와 날짜"
    else:
        date_text = f"{parsed_date:%Y-%m-%d %H:%M:%S} {timezone_label}"
        answer = (
            f"The selected email reports a login from {device}. "
            f"The alert is dated {date_text}."
        )
        section = "Login device and date from the selected Gmail security alert"
    refs = [evidence_ref]
    return GmailSecurityReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": refs},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": refs},
    )


def _supports_request(user_request: str, request_intent: Mapping[str, object]) -> bool:
    lowered = user_request.casefold()
    constraints = request_intent.get("constraints")
    selected = isinstance(constraints, list) and any(
        isinstance(item, Mapping)
        and item.get("kind") == "RESOURCE"
        and item.get("field") in {"resource_id", "selected_resource_id"}
        for item in constraints
    )
    return (
        selected
        and request_intent.get("analysis_requirement") == "NONE"
        and set(_strings(request_intent.get("requested_effect_hints"))) == {"READ"}
        and set(_strings(request_intent.get("requested_resource_hints"))) == {"GMAIL_THREAD"}
        and "로그인" in lowered
        and ("기기" in lowered or "날짜" in lowered)
    )


def _device(excerpt: str) -> str | None:
    for pattern in _DEVICE_PATTERNS:
        match = pattern.search(excerpt)
        if match is not None:
            return match.group(1).strip()
    return None


def _message_date(excerpt: str) -> tuple[datetime, str] | None:
    match = _DATE_HEADER.search(excerpt)
    if match is None:
        return None
    raw_date = match.group(1).strip()
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError):
        return None
    timezone_match = re.search(r"([A-Za-z]{2,5}|[+-]\d{4})$", raw_date)
    return parsed, timezone_match.group(1) if timezone_match is not None else "UTC"


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _strings(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


__all__ = ["GmailSecurityReadAnswerProjection", "project_gmail_security_read_answer"]
