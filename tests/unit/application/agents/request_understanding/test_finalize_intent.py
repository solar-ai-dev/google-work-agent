from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestGoalCandidateV1,
)
from google_work_agent.application.agents.request_understanding.finalize_intent import (
    finalize_intent,
)


def test_finalize_intent__valid_candidates__attaches_application_lineage() -> None:
    goal_candidate: RequestGoalCandidateV1 = {
        "goal": "goal",
        "completion_conditions": ["done"],
        "constraints": [],
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
    }
    intent = finalize_intent(
        goal_candidate,
        {"requires_confirmation": False, "reason_codes": [], "missing_fields": []},
        artifact_id="intent-1",
    )

    assert intent["schema_version"] == 2
    assert intent["meta"] == {"artifact_id": "intent-1", "revision": 1, "based_on": []}
