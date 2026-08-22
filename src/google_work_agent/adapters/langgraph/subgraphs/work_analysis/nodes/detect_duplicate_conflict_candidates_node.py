from google_work_agent.application.agents.work_analysis.detect_duplicate_conflict_candidates import detect_duplicate_conflict_candidates
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.work_analysis_operation_projection import project_work_analysis_operation_input


def detect_duplicate_conflict_candidates_node(state: dict[str, object]) -> dict[str, object]:
    return {"duplicate_conflict_candidates": detect_duplicate_conflict_candidates(**project_work_analysis_operation_input(state, "detect_duplicate_conflict_candidates"))}
