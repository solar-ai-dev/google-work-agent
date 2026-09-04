"""Project grounded user prose when a READ produced no usable evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)


class EmptyReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_empty_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    retrieval_result: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
) -> EmptyReadAnswerProjection | None:
    """Return a natural no-result or partial-failure READ answer without guessing."""

    if (
        evidence
        or retrieval_result is None
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
    ):
        return None

    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    resource = _resource_label(request_intent)
    criteria = _criteria(request_intent)
    scope = f"'{criteria}' 조건으로 " if criteria else ""
    failed = _has_source_failure(retrieval_result)
    no_resources = _returned_no_resources(retrieval_result)

    if korean:
        if failed:
            answer = (
                f"{scope}{resource} 자료를 확인했지만 일부 읽기에 실패해 요청을 완료할 "
                "근거가 부족합니다. Google 연결 상태를 확인한 뒤 다시 시도해 주세요."
            )
            section = "일부 자료 읽기 실패"
        elif no_resources:
            answer = (
                f"{scope}{_object_resource(resource)} 검색했지만 관련 자료를 찾지 못했습니다. "
                "검색어나 기간을 넓혀 다시 요청해 주세요."
            )
            section = "검색 결과 없음"
        else:
            answer = (
                f"{scope}{_object_resource(resource)} 확인했지만 요청에 답할 수 있는 근거가 "
                "충분하지 않습니다. 검색 조건을 보완해 다시 요청해 주세요."
            )
            section = "근거 부족"
    else:
        prefix = f"Using the {criteria} criteria, " if criteria else ""
        if failed:
            answer = (
                f"{prefix}I could not gather enough evidence from {resource} because some "
                "reads failed. Check the Google connection and try again."
            )
            section = "Some sources could not be read"
        elif no_resources:
            answer = (
                f"{prefix}I could not find related material in {resource}. "
                "Try again with broader keywords or a wider date range."
            )
            section = "No matching results"
        else:
            answer = (
                f"{prefix}I could not find enough evidence in {resource} to answer the "
                "request. Refine the search criteria and try again."
            )
            section = "Insufficient evidence"

    return EmptyReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": []},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": []},
    )


def _resource_label(request_intent: Mapping[str, object]) -> str:
    hints = set(_strings(request_intent.get("requested_resource_hints")))
    if hints and all(item.startswith("GMAIL") for item in hints):
        return "Gmail"
    if hints and all(item.startswith("TASK") for item in hints):
        return "Google Tasks"
    if hints and all(item.startswith("CALENDAR") for item in hints):
        return "Google Calendar"
    return "Google Workspace"


def _criteria(request_intent: Mapping[str, object]) -> str:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return ""
    values: list[str] = []
    owned_fields = (
        ("DATE", "period"),
        ("PERSON", "person"),
        ("USER_REQUIREMENT", "search_terms"),
    )
    for kind, field in owned_fields:
        for item in constraints:
            if not isinstance(item, Mapping):
                continue
            if item.get("kind") == kind and item.get("field") == field:
                values.extend(_strings_or_scalar(item.get("value")))
    return " · ".join(dict.fromkeys(values))


def _object_resource(resource: str) -> str:
    return {
        "Gmail": "Gmail을",
        "Google Tasks": "Google Tasks를",
        "Google Calendar": "Google Calendar를",
        "Google Workspace": "Google Workspace를",
    }[resource]


def _has_source_failure(retrieval_result: Mapping[str, object]) -> bool:
    statuses = retrieval_result.get("source_statuses")
    return isinstance(statuses, list) and any(
        isinstance(item, Mapping)
        and (item.get("failure_kind") is not None or item.get("status") == "FAILED")
        for item in statuses
    )


def _returned_no_resources(retrieval_result: Mapping[str, object]) -> bool:
    missing = retrieval_result.get("missing_information")
    return isinstance(missing, list) and any(
        isinstance(item, Mapping) and "RETURNED_NO_RESOURCES" in str(item.get("description", ""))
        for item in missing
    )


def _strings(value: object) -> list[str]:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _strings_or_scalar(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [item for item in values if isinstance(item, str) and item]


__all__ = ["EmptyReadAnswerProjection", "project_empty_read_answer"]
