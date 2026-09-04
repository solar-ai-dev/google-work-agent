"""Project simple Google Tasks reads directly from selected evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)


class TaskReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_task_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> TaskReadAnswerProjection | None:
    """Return one grounded projection only for non-analytical Tasks READs."""
    if (
        request_intent.get("analysis_requirement") != "NONE"
        or set(_strings(request_intent.get("requested_effect_hints"))) != {"READ"}
        or set(_strings(request_intent.get("requested_resource_hints"))) != {"TASK"}
    ):
        return None

    task_items = [item for item in evidence if _resource_handle(item).startswith("task:")]
    citation_items = task_items or [
        item for item in evidence if _resource_handle(item).startswith("task_list:")
    ]
    evidence_refs = [ref for item in citation_items if (ref := _evidence_ref(item)) is not None]
    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    titles = [title for item in task_items if (title := _task_title(item)) is not None]
    if titles:
        lead = (
            f"Google Tasks에서 확인된 현재 할 일은 {len(titles)}개입니다."
            if korean
            else f"I found {len(titles)} current item(s) in Google Tasks."
        )
        answer = f"{lead}\n\n" + "\n".join(f"- {title}" for title in titles)
        section = "현재 Google Tasks 할 일" if korean else "Current Google Tasks items"
    else:
        answer = (
            "Google Tasks에서 현재 표시할 할 일을 찾지 못했습니다."
            if korean
            else "I could not find any current items in Google Tasks."
        )
        section = "검색 결과 없음" if korean else "No current tasks found"
    unique_refs = list(dict.fromkeys(evidence_refs))
    return TaskReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": unique_refs},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": unique_refs},
    )


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _resource_handle(item: Mapping[str, object]) -> str:
    value = item.get("resource_handle") or item.get("resource_ref")
    return value if isinstance(value, str) else ""


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _task_title(item: Mapping[str, object]) -> str | None:
    excerpt = item.get("excerpt")
    if not isinstance(excerpt, str):
        return None
    title = next((line.strip() for line in excerpt.splitlines() if line.strip()), "")
    return title or None


__all__ = ["TaskReadAnswerProjection", "project_task_read_answer"]
