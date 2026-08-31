from collections.abc import Mapping
from typing import NotRequired, TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.normalize_segments import SourceSegment
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagScoringConfig


class RagRetrieveRerankInput(TypedDict):
    segments: list[SourceSegment]
    request_intent: RequestIntentV2
    top_k: int
    config: NotRequired[RagScoringConfig]


def project_rag_retrieve_rerank_input(state: Mapping[str, object]) -> RagRetrieveRerankInput:
    inputs = state.get("operation_inputs")
    value = inputs.get("rag_retrieve_rerank") if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("missing typed input projection for retrieval.rag_retrieve_rerank")
    return cast(RagRetrieveRerankInput, dict(value))
