from google_work_agent.application.agents.retrieval.finalize_retrieval import finalize_retrieval

from ..projections.retrieval_operation_projection import (
    project_retrieval_operation_input,
)


def finalize_retrieval_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "final_result": finalize_retrieval(
            **project_retrieval_operation_input(state, "finalize_retrieval")
        )
    }
