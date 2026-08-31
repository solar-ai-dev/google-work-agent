from __future__ import annotations

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestGoalCandidateV1,
    RequestIntentV2,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)


def finalize_intent(
    goal_candidate: RequestGoalCandidateV1,
    ambiguity_candidate: AmbiguityV1,
    *,
    artifact_id: str,
) -> RequestIntentV2:
    if not artifact_id:
        raise ValueError("artifact_id must be non-empty")
    return validate_intent(
        {
            "schema_version": 2,
            **goal_candidate,
            "ambiguity": ambiguity_candidate,
            "meta": {"artifact_id": artifact_id, "revision": 1, "based_on": []},
        },
        require_meta=True,
    )
