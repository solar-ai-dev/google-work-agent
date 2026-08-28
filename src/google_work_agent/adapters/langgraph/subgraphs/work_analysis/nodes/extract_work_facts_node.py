from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import (
    project_work_analysis_operation_input,
)
from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts


def extract_work_facts_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "work_facts": extract_work_facts(
            **project_work_analysis_operation_input(state, "extract_work_facts")
        )
    }
