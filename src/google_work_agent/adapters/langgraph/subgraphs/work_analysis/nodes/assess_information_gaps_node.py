from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.assess_information_gaps import (
    assess_information_gaps,
)


def assess_information_gaps_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "information_gaps": assess_information_gaps(
            **project_work_analysis_operation_input(state, "assess_information_gaps")
        )
    }
