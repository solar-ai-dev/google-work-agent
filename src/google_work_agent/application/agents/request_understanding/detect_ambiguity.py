from __future__ import annotations

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestIntentCandidateV1,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    validate_intent,
)


def detect_ambiguity(candidate: RequestIntentCandidateV1) -> AmbiguityV1:
    validated = validate_intent(candidate)
    return dict(validated["ambiguity"])  # type: ignore[return-value]
