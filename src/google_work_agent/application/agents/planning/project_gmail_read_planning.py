"""Project Gmail READs onto evidence-grounded Planning inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerOutlineV1,
)

_DECISION_MARKERS = ("결정", "확정", "다음 할 일", "decision", "action item")


class GmailReadPlanningProjection(NamedTuple):
    outline: AnswerOutlineV1


def project_gmail_read_planning(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> GmailReadPlanningProjection | None:
    """Keep final Gmail prose grounded in source evidence, not intermediate analysis text."""

    if (
        not evidence
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
        or not _gmail_only(request_intent.get("requested_resource_hints"))
    ):
        return None

    requested_information = _requested_information(request_intent)
    answer_evidence = (
        _decision_evidence(evidence)
        if _decision_requested(user_request, requested_information)
        else list(evidence)
    )
    evidence_refs = [
        ref for item in answer_evidence if (ref := _evidence_ref(item)) is not None
    ]
    if not evidence_refs:
        return None

    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    if korean:
        sections = ["요청한 Gmail 자료에 근거한 직접 답변"]
        sections.extend(f"확인할 내용: {item}" for item in requested_information)
        sections.append(
            "명시적으로 결정 또는 확정된 내용과 남은 불확실성"
            if _decision_requested(user_request, requested_information)
            else "관련 메일 간 시간 순서, 결정 사항과 남은 불확실성"
        )
    else:
        sections = ["Direct answer grounded in the retrieved Gmail messages"]
        sections.extend(f"Requested information: {item}" for item in requested_information)
        sections.append(
            "Explicit decisions and remaining uncertainty"
            if _decision_requested(user_request, requested_information)
            else "Timeline, decisions, and remaining uncertainty across related messages"
        )

    return GmailReadPlanningProjection(
        outline={
            "sections": list(dict.fromkeys(sections)),
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
        }
    )


def _gmail_only(value: object) -> bool:
    resources = _strings(value)
    return bool(resources) and all(item.startswith("GMAIL") for item in resources)


def _requested_information(request_intent: Mapping[str, object]) -> list[str]:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return []
    values: list[str] = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping) or constraint.get("field") != "required_information":
            continue
        raw = constraint.get("value")
        if isinstance(raw, list):
            values.extend(_strings(raw))
        elif isinstance(raw, str):
            values.append(raw)
    return list(dict.fromkeys(item for item in values if item.strip()))


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _decision_requested(user_request: str, requested_information: Sequence[str]) -> bool:
    combined = " ".join([user_request, *requested_information]).casefold()
    return any(marker in combined for marker in _DECISION_MARKERS)


def _decision_evidence(
    evidence: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    selected = [
        item
        for item in evidence
        if isinstance(item.get("excerpt"), str)
        and any(marker in str(item["excerpt"]).casefold() for marker in _DECISION_MARKERS)
    ]
    return selected or list(evidence)


__all__ = ["GmailReadPlanningProjection", "project_gmail_read_planning"]
