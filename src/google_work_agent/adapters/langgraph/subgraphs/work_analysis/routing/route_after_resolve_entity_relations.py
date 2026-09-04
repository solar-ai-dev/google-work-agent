from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)
from google_work_agent.application.agents.work_analysis.resolve_temporal_dependencies import (
    temporal_dependency_candidate_llm_required,
)


def route_after_resolve_entity_relations(state: object) -> str:
    if isinstance(state, Mapping):
        facts = state.get("fact_candidates")
        if isinstance(facts, list) and not temporal_dependency_candidate_llm_required(
            cast(list[WorkFactV1], facts)
        ):
            return "detect_duplicate_conflict_candidates"
    return "resolve_temporal_dependencies"
