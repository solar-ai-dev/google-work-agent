from copy import deepcopy

import pytest

from google_work_agent.application.agents.request_understanding.validate_intent import (
    RequestUnderstandingValidationError,
    validate_intent,
)


def _candidate() -> dict[str, object]:
    return {
        "schema_version": 2,
        "goal": "김대리 관련 메일에서 할 일 정리",
        "completion_conditions": ["할 일을 요약한다"],
        "constraints": [{"kind": "PERSON", "field": "person", "value": "김대리"}],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["GMAIL_THREAD"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }


def test_validate_intent__canonical_candidate__preserves_contract() -> None:
    assert validate_intent(_candidate())["goal"] == "김대리 관련 메일에서 할 일 정리"


def test_validate_intent__unknown_schema__fails_closed() -> None:
    invalid = deepcopy(_candidate())
    invalid["schema_version"] = 99
    with pytest.raises(RequestUnderstandingValidationError, match="schema_version"):
        validate_intent(invalid)
