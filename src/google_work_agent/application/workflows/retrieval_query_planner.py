"""LLM-only Retrieval query planner with injected prompt dependencies."""

from __future__ import annotations

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.retrieval_query_plan import (
    RouteQueryIntentV1,
    validate_followup_route_query_intent,
)
from google_work_agent.application.workflows.handoff_contracts import SufficiencyIssueV2
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.ports import OutputSchemaDefinition, PromptReference


class RetrievalQueryPlannerAgent:
    """Produce semantic RouteQueryIntent proposals; never execute a read."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference,
        output_schema: OutputSchemaDefinition,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref
        self._output_schema = output_schema

    def plan(
        self,
        *,
        prompt_input: dict[str, object],
        trace_context: ObservabilityContext,
        frozen_route: ToolRoutePlanV2,
        unresolved_issues: list[SufficiencyIssueV2],
        detail_candidate_refs: frozenset[str],
    ) -> list[RouteQueryIntentV1]:
        """Invoke the injected slot and fail before execution on invalid output."""
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=prompt_input,
            output_schema=self._output_schema,
            trace_context=trace_context,
        )
        payload = result.structured_output
        if not isinstance(payload, dict) or not isinstance(payload.get("route_queries"), list):
            raise ValueError("invalid RetrievalQueryPlanV1")
        return [
            validate_followup_route_query_intent(
                value=item,
                frozen_route=frozen_route,
                unresolved_issues=unresolved_issues,
                detail_candidate_refs=detail_candidate_refs,
            )
            for item in payload["route_queries"]
        ]
