"""Compatibility delegates to canonical Retrieval-local RAG ranking."""

from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    DEFAULT_RAG_SCORING_CONFIG,
    RagCandidateV1,
    RagScoringConfig,
    rag_retrieve_rerank,
)

EXACT_RESOURCE_REASON = "EXACT_RESOURCE"
RELATED_RESOURCE_REASON = "RELATED_RESOURCE"
KEYWORD_MATCH_REASON = "KEYWORD_MATCH"
RESOURCE_SELECTED_FORCED_REASON = "RESOURCE_SELECTED_FORCED"

rank_segments = rag_retrieve_rerank

__all__ = [
    "DEFAULT_RAG_SCORING_CONFIG",
    "EXACT_RESOURCE_REASON",
    "KEYWORD_MATCH_REASON",
    "RELATED_RESOURCE_REASON",
    "RESOURCE_SELECTED_FORCED_REASON",
    "RagCandidateV1",
    "RagScoringConfig",
    "rank_segments",
]
