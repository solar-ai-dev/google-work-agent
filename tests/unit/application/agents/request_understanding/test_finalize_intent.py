from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)


def test_finalize_intent__valid_candidate__attaches_application_lineage() -> None:
    candidate = {
        "schema_version": 2,
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
    }
    intent = finalize_intent(candidate, artifact_id="intent-1")
    assert intent["meta"] == {"artifact_id": "intent-1", "revision": 1, "based_on": []}
