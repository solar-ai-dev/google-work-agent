from __future__ import annotations

from typing import NotRequired

from google_work_agent.adapters.langgraph.subgraph_state import (
    RequestUnderstandingInputState,
    RequestUnderstandingLocalState,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    RequestIntentCandidateV1,
    RequestIntentV2,
)
from google_work_agent.application.workflows import ConfirmationResponseV1


class RequestUnderstandingState(RequestUnderstandingLocalState, total=False):
    """Owner-local working fields for Request Understanding only."""

    ru_candidate: NotRequired[RequestIntentCandidateV1]
    ru_ambiguity: NotRequired[AmbiguityV1]
    ru_intent: NotRequired[RequestIntentV2]
    ru_confirmation_response: NotRequired[ConfirmationResponseV1 | None]
