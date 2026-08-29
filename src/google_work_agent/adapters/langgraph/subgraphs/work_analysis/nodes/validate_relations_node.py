# ruff: noqa: E501

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.validate_relations_projection import (
    project_validate_relations_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.validate_relations import validate_relations


def validate_relations_node(state: WorkAnalysisStateV2) -> WorkAnalysisStateV2:
    return validate_relations(**project_validate_relations_input(state))
