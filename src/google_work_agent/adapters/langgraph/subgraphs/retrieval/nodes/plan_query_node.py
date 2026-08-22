from google_work_agent.application.agents.retrieval.plan_query import plan_query
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def plan_query_node(state: dict[str, object]) -> dict[str, object]:
    return {"query_plan": plan_query(**project_retrieval_operation_input(state, "plan_query"))}
