from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.validate_relations import validate_relations


def validate_relations_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "validated_relations": validate_relations(
            **project_work_analysis_operation_input(state, "validate_relations")
        )
    }
