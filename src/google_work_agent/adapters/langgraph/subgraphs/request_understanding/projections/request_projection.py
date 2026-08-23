from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import request_from_state
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.state import (
    RequestUnderstandingState,
)


def project_request_input(state: RequestUnderstandingState) -> dict[str, object]:
    """Allowlist the current-run request fields consumed by identify_goal."""

    request = request_from_state(state)
    projected: dict[str, object] = {"request": request}
    confirmation = state.get("ru_confirmation_response")
    if confirmation is not None:
        projected["confirmation_response"] = confirmation
    return projected
