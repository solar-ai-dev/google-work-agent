from google_work_agent.application.agents.request_understanding.detect_ambiguity import (
    detect_ambiguity,
)


def test_detect_ambiguity__confirmation_required__returns_owned_ambiguity() -> None:
    candidate = {
        "schema_version": 2,
        "goal": "일정 정리",
        "completion_conditions": ["정리"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["CALENDAR_EVENT"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {
            "requires_confirmation": True,
            "reason_codes": ["INTENT_AMBIGUITY_MISSED"],
            "missing_fields": ["대상 인물"],
        },
    }
    assert detect_ambiguity(candidate)["requires_confirmation"] is True
