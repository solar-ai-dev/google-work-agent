from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def normalize_segments_node(state: dict[str, object]) -> dict[str, object]:
    return {"segments": normalize_segments(**project_retrieval_operation_input(state, "normalize_segments"))}
