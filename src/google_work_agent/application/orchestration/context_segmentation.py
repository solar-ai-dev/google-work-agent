"""Compatibility delegates to canonical Retrieval segment normalization."""

from google_work_agent.application.agents.retrieval.normalize_segments import (
    DEFAULT_CONTEXT_BUDGET,
    ContextBudget,
    SourceSegment,
    _chunk_text,
    _estimate_tokens,
    _resource_text,
    _strip_email_quote_and_signature,
    _truncate,
    normalize_segments,
)
from google_work_agent.application.orchestration.handoff_contracts import AcquisitionResultV1

_SourceSegment = SourceSegment


class ContextRetrievalValidationError(ValueError):
    """Legacy validation error name retained for #114 consumers."""


def _segments_from_acquisition(
    acquisition_result: AcquisitionResultV1,
    context_budget: ContextBudget,
) -> list[SourceSegment]:
    return normalize_segments(acquisition_result, context_budget=context_budget)


__all__ = [
    "ContextBudget",
    "ContextRetrievalValidationError",
    "DEFAULT_CONTEXT_BUDGET",
    "_SourceSegment",
    "_chunk_text",
    "_estimate_tokens",
    "_resource_text",
    "_segments_from_acquisition",
    "_strip_email_quote_and_signature",
    "_truncate",
]
