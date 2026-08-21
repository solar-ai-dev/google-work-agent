from __future__ import annotations

from google_work_agent.application.agents.request_understanding.contracts.request_intent import RequestIntentCandidateV1, RequestIntentV2
from google_work_agent.application.agents.request_understanding.validate_intent import validate_intent

def finalize_intent(candidate: RequestIntentCandidateV1, *, artifact_id: str) -> RequestIntentV2:
    if not artifact_id:
        raise ValueError("artifact_id must be non-empty")
    validated = validate_intent(candidate)
    return {**validated, "meta": {"artifact_id": artifact_id, "revision": 1, "based_on": []}}  # type: ignore[return-value]
