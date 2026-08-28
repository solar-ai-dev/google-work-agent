from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.resolve_entity_relations import (
    resolve_entity_relations,
)


def resolve_entity_relations_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "entity_relations": resolve_entity_relations(
            **project_work_analysis_operation_input(state, "resolve_entity_relations")
        )
    }
