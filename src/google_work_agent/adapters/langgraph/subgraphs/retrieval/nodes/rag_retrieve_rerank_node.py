from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import rag_retrieve_rerank

from ..projections.rag_retrieve_rerank_projection import project_rag_retrieve_rerank_input
from ..state import RetrievalState


def rag_retrieve_rerank_node(state: RetrievalState) -> dict[str, object]:
    return {"rag_candidates": rag_retrieve_rerank(**project_rag_retrieve_rerank_input(state))}
