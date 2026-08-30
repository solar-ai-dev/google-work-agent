# ruff: noqa: E501

from google_work_agent.adapters.langgraph.subgraph_state import WorkAnalysisLocalState
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.projections.resolve_entity_relations_projection import (
    project_resolve_entity_relations_input,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.resolve_entity_relations import (
    resolve_entity_relations,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


def resolve_entity_relations_node(
    state: WorkAnalysisLocalState,
    *,
    llm_runtime: StructuredLLMRuntime,
    prompt_ref: PromptReference,
    trace_context: ObservabilityContext,
    confirmation_response: dict[str, object] | None = None,
) -> WorkAnalysisStateV2:
    return {
        "entity_relation_candidates": resolve_entity_relations(
            **project_resolve_entity_relations_input(state),
            llm_runtime=llm_runtime,
            prompt_ref=prompt_ref,
            trace_context=trace_context,
            confirmation_response=confirmation_response,
        )
    }
