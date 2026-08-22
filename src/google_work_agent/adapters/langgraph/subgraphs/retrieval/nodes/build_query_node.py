from google_work_agent.application.agents.retrieval.build_query import build_query
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def build_query_node(state: dict[str, object]) -> dict[str, object]:
    return {"fetch_plan": build_query(**project_retrieval_operation_input(state, "build_query"))}
