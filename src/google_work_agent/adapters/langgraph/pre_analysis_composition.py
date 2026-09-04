"""Construction-only composition for the request-to-retrieval graph entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    RetrievalSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import (
    build_tool_routing_subgraph,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
)
from google_work_agent.application.prompt_runtime.prompt_registry import PromptExecutionScope
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort


@dataclass(frozen=True, slots=True)
class PreAnalysisSubgraphs:
    request_understanding: Any
    tool_route: Any
    context_retrieval: Any


def build_pre_analysis_subgraphs(
    *,
    llm_runtime: StructuredInferencePort,
    prompt_manifest_path: Path | None,
    prompt_execution_scope: PromptExecutionScope,
    connector_reader: ConnectorReadPort,
    tool_catalog: SignedToolRegistry,
    id_factory: Callable[[], str],
    graph_profile: GraphProfile,
    transition_run: Callable[[str, str], None],
    merge_decision: Callable[..., Any],
    confirm_request_understanding_inline: Callable[
        [Any], tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]
    ],
    confirm_tool_route_inline: Callable[
        [Any], tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]
    ],
    confirm_context_retrieval_inline: Callable[
        [Any], tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]
    ],
    evidence_store: RunScopedEvidenceStore,
    read_result_cache: RunRetrievalCachePort,
    now_ms: Callable[[], int],
    timezone_provider: Callable[[], str],
    default_tasklist_id_provider: Callable[[], str | None] | None = None,
    default_calendar_id_provider: Callable[[], str | None] | None = None,
) -> PreAnalysisSubgraphs:
    """Create nodes only; workflow policy remains in their Application owners."""

    return PreAnalysisSubgraphs(
        request_understanding=RequestUnderstandingSubgraph(
            llm_runtime=llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            prompt_execution_scope=prompt_execution_scope,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
            confirm_inline=confirm_request_understanding_inline,
        ).build(),
        tool_route=build_tool_routing_subgraph(
            tool_catalog=tool_catalog,
            llm_runtime=llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            prompt_execution_scope=prompt_execution_scope,
            id_factory=id_factory,
            merge_decision=merge_decision,
            graph_profile=graph_profile,
            confirm_inline=confirm_tool_route_inline,
        ),
        context_retrieval=RetrievalSubgraph(
            llm_runtime=llm_runtime,
            prompt_manifest_path=prompt_manifest_path,
            prompt_execution_scope=prompt_execution_scope,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
            evidence_store=evidence_store,
            connector_reader=connector_reader,
            tool_catalog=tool_catalog,
            read_result_cache=read_result_cache,
            confirm_inline=confirm_context_retrieval_inline,
            now_ms=now_ms,
            timezone_provider=timezone_provider,
            default_tasklist_id_provider=default_tasklist_id_provider,
            default_calendar_id_provider=default_calendar_id_provider,
        ).build(),
    )


__all__ = ["PreAnalysisSubgraphs", "build_pre_analysis_subgraphs"]
