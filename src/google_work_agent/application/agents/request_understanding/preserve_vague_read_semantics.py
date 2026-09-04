"""Preserve user-owned search meaning for vague Google Workspace reads."""

from __future__ import annotations

import re

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    ConstraintKindValue,
    ConstraintV1,
    RequestGoalCandidateV1,
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "n/a",
        "na",
        "none",
        "null",
        "unknown",
        "unspecified",
        "not provided",
        "not specified",
        "미상",
        "알 수 없음",
    }
)
_PERSON_PATTERN = re.compile(r"[가-힣]{1,4}(?:대리|과장|차장|부장|팀장|실장|이사|님)")
_PERIOD_PATTERN = re.compile(
    r"지난\s*주|이번\s*주|다음\s*주|지난\s*달|이번\s*달|최근|오늘|어제|그제"
)
_DIRECT_TOPIC_PATTERNS = (
    re.compile(r"(?P<topic>[0-9A-Za-z가-힣_+\-]{2,})\s*(?:관련|에\s*관한)\s*(?:메일|이메일)"),
    re.compile(r"(?P<topic>[0-9A-Za-z가-힣_+\-]{2,})\s*(?:메일|이메일)"),
)
_DISCUSSED_TOPIC_PATTERN = re.compile(
    r"(?P<topic>(?:[0-9A-Za-z가-힣_+\-]+\s+){0,3}[0-9A-Za-z가-힣_+\-]+)\s*"
    r"(?:얘기한|얘기했던|이야기한|이야기했던|논의한|논의했던)\s*(?:메일|이메일)"
)
_TOPIC_STOPWORDS = frozenset(
    {
        "관련",
        "메일",
        "이메일",
        "최근",
        "지난주",
        "지난주에",
        "이번주",
        "이번주에",
        "다음주",
        "다음주에",
        "지난달",
        "지난달에",
        "이번달",
        "이번달에",
        "얘기한",
        "얘기했던",
        "이야기한",
        "이야기했던",
        "논의한",
        "논의했던",
    }
)
_FALLBACK_BUSINESS_TOPICS = (
    "회의",
    "프로젝트",
    "일정",
    "예산",
    "계약",
    "채용",
    "출시",
    "보고서",
    "장애",
    "보안",
)


def preserve_vague_read_semantics(
    candidate: RequestGoalCandidateV1,
    *,
    request_text: str,
    entry_mode: str,
) -> RequestGoalCandidateV1:
    """Keep executable Gmail search facts even when local inference omits them."""

    if (
        entry_mode != "AGENT_SEARCH"
        or candidate["requested_effect_hints"] != ["READ"]
        or "GMAIL_THREAD" not in candidate["requested_resource_hints"]
    ):
        return candidate

    constraints = _without_unstated_placeholders(candidate["constraints"], request_text)
    _merge_constraint(
        constraints,
        kind="USER_REQUIREMENT",
        field="original_search_request",
        values=[request_text],
        replace_existing=True,
    )
    _merge_constraint(
        constraints,
        kind="USER_REQUIREMENT",
        field="search_terms",
        values=_search_topics(request_text),
        replace_existing=True,
    )
    _merge_constraint(
        constraints,
        kind="PERSON",
        field="person",
        values=[match.group(0) for match in _PERSON_PATTERN.finditer(request_text)],
        replace_existing=True,
    )
    _merge_constraint(
        constraints,
        kind="DATE",
        field="period",
        values=[
            match.group(0).replace(" ", "") for match in _PERIOD_PATTERN.finditer(request_text)
        ],
        replace_existing=True,
    )
    _merge_constraint(
        constraints,
        kind="USER_REQUIREMENT",
        field="required_information",
        values=_required_information(request_text),
    )
    return {**candidate, "constraints": constraints}


def _without_unstated_placeholders(
    constraints: list[ConstraintV1], request_text: str
) -> list[ConstraintV1]:
    request_normalized = request_text.casefold()
    result: list[ConstraintV1] = []
    for constraint in constraints:
        raw_value = constraint["value"]
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        retained = [
            value
            for value in values
            if value.casefold().strip() not in _PLACEHOLDER_VALUES
            or value.casefold().strip() in request_normalized
        ]
        if not retained:
            continue
        result.append(
            {
                **constraint,
                "value": retained if isinstance(raw_value, list) else retained[0],
            }
        )
    return result


def _search_topics(request_text: str) -> list[str]:
    topics: list[str] = []
    people = {match.group(0) for match in _PERSON_PATTERN.finditer(request_text)}
    for pattern in _DIRECT_TOPIC_PATTERNS:
        topics.extend(match.group("topic") for match in pattern.finditer(request_text))
    for match in _DISCUSSED_TOPIC_PATTERN.finditer(request_text):
        topics.extend(
            token
            for token in match.group("topic").split()
            if token not in _TOPIC_STOPWORDS
            and not any(token.startswith(person) for person in people)
        )
    if not topics:
        topics.extend(topic for topic in _FALLBACK_BUSINESS_TOPICS if topic in request_text)
    return list(dict.fromkeys(topic for topic in topics if topic not in _TOPIC_STOPWORDS))


def _required_information(request_text: str) -> list[str]:
    required: list[str] = []
    if re.search(r"일정(?:을|은|이)?\s*(?:정리|요약|알려)", request_text):
        required.append("일정")
    if re.search(r"해야\s*할\s*일|할\s*일(?:을|은|이)?\s*(?:정리|요약|알려)", request_text):
        required.append("해야 할 일")
    if re.search(r"후속\s*(?:작업|조치)", request_text):
        required.append("후속 작업")
    if re.search(r"최신\s*(?:결정|결론)", request_text):
        required.append("최신 결정")
    return required


def _merge_constraint(
    constraints: list[ConstraintV1],
    *,
    kind: ConstraintKindValue,
    field: str,
    values: list[str],
    replace_existing: bool = False,
) -> None:
    values = list(dict.fromkeys(value for value in values if value))
    if not values:
        return
    existing = next(
        (
            constraint
            for constraint in constraints
            if constraint["kind"] == kind and constraint["field"] == field
        ),
        None,
    )
    if existing is None:
        constraints.append({"kind": kind, "field": field, "value": values})
        return
    if replace_existing:
        existing["value"] = (
            values if isinstance(existing["value"], list) or len(values) > 1 else values[0]
        )
        return
    current = existing["value"]
    current_values = current if isinstance(current, list) else [current]
    merged = list(dict.fromkeys([*current_values, *values]))
    existing["value"] = merged if isinstance(current, list) or len(merged) > 1 else merged[0]


__all__ = ["preserve_vague_read_semantics"]
