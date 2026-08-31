from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.validate_relations import (
    RelationValidationBundleV1,
    validate_relations,
)

from ..projections.validate_relations_projection import (
    project_validate_relations_input,
)


def validate_relations_node(state: WorkAnalysisLocalState) -> RelationValidationBundleV1:
    return validate_relations(**project_validate_relations_input(state))
