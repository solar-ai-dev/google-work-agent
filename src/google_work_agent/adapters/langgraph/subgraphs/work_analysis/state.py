"""Owner-local LangGraph state for Work Analysis."""

from __future__ import annotations

from typing import NotRequired, TypedDict


class WorkAnalysisState(TypedDict):
    """Invocation-local state. Only analysis_result/workflow_signal are parent-facing patches."""

    operation_inputs: dict[str, dict[str, object]]
    work_facts: NotRequired[object]
    entity_relations: NotRequired[object]
    temporal_relations: NotRequired[object]
    duplicate_conflict_candidates: NotRequired[object]
    validated_relations: NotRequired[object]
    information_gaps: NotRequired[object]
    operational_risks: NotRequired[object]
    assembled_analysis: NotRequired[object]
    analysis_result: NotRequired[object]
    workflow_signal: NotRequired[object]
