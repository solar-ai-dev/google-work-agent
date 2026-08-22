from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def project_candidate_input(state: RequestUnderstandingState) -> dict[str, object]:
    """Allowlist the Request Understanding candidate only."""

    candidate = state.get("ru_candidate")
    if candidate is None:
        raise ValueError("request-understanding candidate is required")
    return {"candidate": candidate}
