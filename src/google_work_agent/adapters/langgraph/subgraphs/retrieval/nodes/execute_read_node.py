from google_work_agent.application.agents.retrieval.execute_read import execute_read
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def execute_read_node(state: dict[str, object]) -> dict[str, object]:
    return {"read_result": execute_read(**project_retrieval_operation_input(state, "execute_read"))}
