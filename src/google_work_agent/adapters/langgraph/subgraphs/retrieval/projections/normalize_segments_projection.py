from collections.abc import Mapping
from typing import NotRequired, TypedDict, cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.normalize_segments import ContextBudget


class NormalizeSegmentsInput(TypedDict):
    acquisition_result: AcquisitionResultV1
    context_budget: NotRequired[ContextBudget]


def project_normalize_segments_input(state: Mapping[str, object]) -> NormalizeSegmentsInput:
    inputs = state.get("operation_inputs")
    value = inputs.get("normalize_segments") if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("missing typed input projection for retrieval.normalize_segments")
    return cast(NormalizeSegmentsInput, dict(value))
