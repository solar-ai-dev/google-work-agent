"""User-language projection for Request Understanding confirmation."""

from __future__ import annotations

import re

from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
)

_KOREAN_FIELD_LABELS = {
    "recipient": "받는 사람",
    "recipient_email": "받는 사람 이메일",
    "date": "날짜",
    "start_time": "시작 시간",
    "end_time": "종료 시간",
    "duration": "소요 시간",
    "title": "제목",
    "calendar_id": "대상 캘린더",
    "task_list_id": "대상 할 일 목록",
    "analysis_focus": "분석 관점",
}


def build_request_clarification_question(
    *,
    request_text: str,
    ambiguity: AmbiguityV1,
    goal_candidate: RequestGoalCandidateV1,
) -> request_understanding_output.ClarificationQuestionV1:
    missing_fields = list(ambiguity["missing_fields"])
    return {
        "schema_version": 1,
        "origin_target": "request.detect_ambiguity",
        "question": _question_for_request(request_text, missing_fields),
        "affected_field_paths": missing_fields,
        "reason_code": (
            ambiguity["reason_codes"][0]
            if ambiguity["reason_codes"]
            else "REQUEST_UNDERSTANDING_NEEDS_CONFIRMATION"
        ),
        "known_context_summary": goal_candidate["goal"],
        "options": [],
    }


def _question_for_request(request_text: str, missing_fields: list[str]) -> str:
    if re.search(r"[가-힣]", request_text):
        labels = [_KOREAN_FIELD_LABELS.get(_field_name(item)) for item in missing_fields]
        if labels and all(label is not None for label in labels):
            known_labels = [label for label in labels if label is not None]
            return (
                "요청을 진행하려면 다음 정보를 알려주세요: "
                f"{', '.join(known_labels)}."
            )
        return (
            "요청을 진행하는 데 필요한 선택 사항이 있습니다. "
            "원하는 내용을 조금 더 구체적으로 알려주세요."
        )
    english_labels = [item.replace("_", " ").replace(".", " ") for item in missing_fields]
    return (
        f"To continue, please provide: {', '.join(english_labels)}."
        if english_labels
        else "Please provide the missing choice needed to continue."
    )


def _field_name(value: str) -> str:
    return value.rsplit(".", 1)[-1].replace("[]", "").casefold()


__all__ = ["build_request_clarification_question"]
