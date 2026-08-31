from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
    WorkAnalysisStateV2,
)
from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.workflow_handoff import RequestedModeV1

from ..projections.extract_work_facts_projection import (
    project_extract_work_facts_input,
)


def extract_work_facts_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredInferencePort,
    prompt_ref: PromptReference,
    requested_mode: RequestedModeV1,
) -> WorkAnalysisStateV2:
    return {
        "fact_candidates": extract_work_facts(
            **project_extract_work_facts_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            requested_mode=requested_mode,
        )
    }
