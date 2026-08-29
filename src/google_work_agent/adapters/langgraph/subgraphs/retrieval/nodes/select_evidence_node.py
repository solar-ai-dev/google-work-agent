from google_work_agent.application.agents.retrieval.select_evidence import select_evidence

from ..projections.retrieval_operation_projection import (
    project_retrieval_operation_input,
)


def select_evidence_node(state: dict[str, object]) -> dict[str, object]:
    return {
        "evidence_selection": select_evidence(
            **project_retrieval_operation_input(state, "select_evidence")
        )
    }
