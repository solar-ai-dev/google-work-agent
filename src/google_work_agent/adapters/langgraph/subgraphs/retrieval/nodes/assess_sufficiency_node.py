from google_work_agent.application.agents.retrieval.assess_sufficiency import assess_sufficiency
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def assess_sufficiency_node(state: dict[str, object]) -> dict[str, object]:
    return {"sufficiency": assess_sufficiency(**project_retrieval_operation_input(state, "assess_sufficiency"))}
