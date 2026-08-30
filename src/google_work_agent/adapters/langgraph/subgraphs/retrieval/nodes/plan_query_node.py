from google_work_agent.application.agents.retrieval.plan_query import plan_query

from ..projections.plan_query_projection import project_plan_query_input
from ..state import RetrievalState


def plan_query_node(state: RetrievalState) -> dict[str, object]:
    query_plan, retry_budget = plan_query(**project_plan_query_input(state))
    return {"query_plan": query_plan, "retry_budget": retry_budget}
