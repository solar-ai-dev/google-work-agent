from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments

from ..projections.normalize_segments_projection import project_normalize_segments_input
from ..state import RetrievalState


def normalize_segments_node(state: RetrievalState) -> dict[str, object]:
    segments = normalize_segments(**project_normalize_segments_input(state))
    return {"segment_handles": [segment.segment_id for segment in segments]}
