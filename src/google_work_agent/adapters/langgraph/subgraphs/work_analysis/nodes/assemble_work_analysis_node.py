from google_work_agent.application.agents.work_analysis.assemble_work_analysis import assemble_work_analysis
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import project_work_analysis_operation_input


def assemble_work_analysis_node(state: dict[str, object]) -> dict[str, object]:
    return {"assembled_analysis": assemble_work_analysis(**project_work_analysis_operation_input(state, "assemble_work_analysis"))}
