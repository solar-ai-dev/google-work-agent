from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank
from google_work_agent.adapters.langgraph.subgraphs.retrieval.projections.retrieval_operation_projection import project_retrieval_operation_input


def rag_retrieve_rerank_node(state: dict[str, object]) -> dict[str, object]:
    return {"ranked_segments": rag_retrieve_rerank(**project_retrieval_operation_input(state, "rag_retrieve_rerank"))}
