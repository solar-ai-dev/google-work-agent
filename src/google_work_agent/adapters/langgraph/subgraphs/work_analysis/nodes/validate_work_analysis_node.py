from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.validate_work_analysis import (
    validate_work_analysis,
)


def validate_work_analysis_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "analysis_result": validate_work_analysis(
            **project_work_analysis_operation_input(state, "validate_work_analysis")
        )
    }
