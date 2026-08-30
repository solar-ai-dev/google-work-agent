# ruff: noqa: E501

from google_work_agent.adapters.langgraph.subgraph_state import WorkAnalysisLocalState
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.extract_work_facts_projection import (
    project_extract_work_facts_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def extract_work_facts_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
) -> WorkAnalysisStateV2:
    return {
        "fact_candidates": extract_work_facts(
            **project_extract_work_facts_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            trace_context=trace_context,
        )
    }
