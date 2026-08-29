from google_work_agent.application.agents.retrieval.execute_read import execute_read

from ..projections.execute_read_projection import project_execute_read_input
from ..state import RetrievalState


def execute_read_node(state: RetrievalState) -> dict[str, object]:
    result = execute_read(**project_execute_read_input(state))
    return {"read_result_handles": [result.read_result_handle]}
