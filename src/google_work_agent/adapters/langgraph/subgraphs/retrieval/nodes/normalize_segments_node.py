from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments

from ..projections.normalize_segments_projection import project_normalize_segments_input
from ..state import RetrievalState


def normalize_segments_node(state: RetrievalState) -> RetrievalState:
    return {"segments": normalize_segments(**project_normalize_segments_input(state))}
