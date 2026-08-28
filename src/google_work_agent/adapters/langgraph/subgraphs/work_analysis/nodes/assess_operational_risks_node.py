from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.assess_operational_risks import (
    assess_operational_risks,
)


def assess_operational_risks_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "operational_risks": assess_operational_risks(
            **project_work_analysis_operation_input(state, "assess_operational_risks")
        )
    }
