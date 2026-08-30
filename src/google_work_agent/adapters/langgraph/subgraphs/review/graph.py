# ruff: noqa: E501
"""Canonical Review owner-local LangGraph composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.aggregate_review_findings_node import (
    aggregate_review_findings_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_action_scope_and_route_node import (
    inspect_action_scope_and_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_constraints_and_policy_summary_node import (
    inspect_constraints_and_policy_summary_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_goal_and_evidence_node import (
    inspect_goal_and_evidence_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.recheck_affected_dimensions_node import (
    recheck_affected_dimensions_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.nodes.validate_review_node import (
    validate_review_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_entry import (
    route_after_entry,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_action_scope_and_route import (
    route_after_inspect_action_scope_and_route,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_constraints_and_policy_summary import (
    route_after_inspect_constraints_and_policy_summary,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_goal_and_evidence import (
    route_after_inspect_goal_and_evidence,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_validation import (
    route_after_validation,
)
from google_work_agent.adapters.langgraph.subgraphs.review.state import ReviewState
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    REVIEW_INSPECT_ACTION_SCOPE_AND_ROUTE_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    REVIEW_INSPECT_CONSTRAINTS_AND_POLICY_SUMMARY_OUTPUT_SCHEMA,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    REVIEW_INSPECT_GOAL_AND_EVIDENCE_OUTPUT_SCHEMA,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import OutputSchemaDefinition, PromptReference, StructuredLLMResult
from google_work_agent.ports.system.contracts.observability import ObservabilityContext


@dataclass(frozen=True, slots=True)
class ReviewRuntimeDependencies:
    """Infrastructure-only dependencies required by canonical Review operations."""

    invoke: ReviewSemanticInvoker


class ReviewSubgraph:
    def __init__(
        self,
        *,
        dependencies: ReviewRuntimeDependencies | None = None,
        llm_runtime: StructuredLLMRuntime | None = None,
        prompt_manifest_path: Path | None = None,
        **_integration: Any,
    ) -> None:
        if dependencies is not None and llm_runtime is not None:
            raise ValueError("supply either ReviewRuntimeDependencies or llm_runtime")
        self._dependencies = dependencies
        self._llm_runtime = llm_runtime
        self._prompt_manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._prompt_refs: dict[str, PromptReference] = {}

    def build(self) -> Any:
        graph = StateGraph(ReviewState)
        graph.add_node(  # type: ignore[type-var]
            "inspect_goal_and_evidence",
            self._inspect_goal_and_evidence_node,
        )
        graph.add_node(  # type: ignore[type-var]
            "inspect_action_scope_route",
            self._inspect_action_scope_and_route_node,
        )
        graph.add_node(  # type: ignore[type-var]
            "inspect_constraints_policy",
            self._inspect_constraints_and_policy_summary_node,
        )
        graph.add_node(  # type: ignore[type-var]
            "aggregate_review_findings", aggregate_review_findings_node
        )
        graph.add_node("validate_review", validate_review_node)  # type: ignore[type-var]
        graph.add_node(  # type: ignore[type-var]
            "recheck_affected_dimensions",
            self._recheck_affected_dimensions_node,
        )
        graph.add_conditional_edges(
            START,
            route_after_entry,
            {
                "inspect_goal_and_evidence": "inspect_goal_and_evidence",
                "recheck_affected_dimensions": "recheck_affected_dimensions",
            },
        )
        graph.add_conditional_edges(
            "inspect_goal_and_evidence",
            route_after_inspect_goal_and_evidence,
            {
                "inspect_action_scope_route": "inspect_action_scope_route",
                "inspect_constraints_policy": "inspect_constraints_policy",
                "aggregate_findings": "aggregate_review_findings",
            },
        )
        graph.add_conditional_edges(
            "inspect_action_scope_route",
            route_after_inspect_action_scope_and_route,
            {
                "inspect_constraints_policy": "inspect_constraints_policy",
                "aggregate_findings": "aggregate_review_findings",
            },
        )
        graph.add_conditional_edges(
            "inspect_constraints_policy",
            route_after_inspect_constraints_and_policy_summary,
            {"aggregate_findings": "aggregate_review_findings"},
        )
        graph.add_edge("recheck_affected_dimensions", "aggregate_review_findings")
        graph.add_edge("aggregate_review_findings", "validate_review")
        graph.add_conditional_edges(
            "validate_review",
            route_after_validation,
            {"end": END},
        )
        return graph.compile(name="review_subgraph")

    def _inspect_goal_and_evidence_node(self, state: Mapping[str, object]) -> dict[str, object]:
        return inspect_goal_and_evidence_node(state, invoke=self.semantic_invoker(state))

    def _inspect_action_scope_and_route_node(
        self, state: Mapping[str, object]
    ) -> dict[str, object]:
        return inspect_action_scope_and_route_node(state, invoke=self.semantic_invoker(state))

    def _inspect_constraints_and_policy_summary_node(
        self, state: Mapping[str, object]
    ) -> dict[str, object]:
        return inspect_constraints_and_policy_summary_node(
            state, invoke=self.semantic_invoker(state)
        )

    def _recheck_affected_dimensions_node(self, state: Mapping[str, object]) -> dict[str, object]:
        if self._dependencies is None:
            raise RuntimeError("review.recheck production cut-over belongs to issue #120")
        return recheck_affected_dimensions_node(state, invoke=self._dependencies.invoke)

    def semantic_invoker(
        self,
        state: Mapping[str, object],
        *,
        on_result: Callable[[StructuredLLMResult], None] | None = None,
    ) -> ReviewSemanticInvoker:
        if self._dependencies is not None:
            return self._dependencies.invoke
        if self._llm_runtime is None:
            raise RuntimeError("Review semantic runtime dependency is required")
        llm_runtime = self._llm_runtime

        def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
            schemas: dict[str, OutputSchemaDefinition] = {
                "review.inspect_goal_and_evidence": (
                    REVIEW_INSPECT_GOAL_AND_EVIDENCE_OUTPUT_SCHEMA
                ),
                "review.inspect_action_scope_and_route": (
                    REVIEW_INSPECT_ACTION_SCOPE_AND_ROUTE_OUTPUT_SCHEMA
                ),
                "review.inspect_constraints_and_policy_summary": (
                    REVIEW_INSPECT_CONSTRAINTS_AND_POLICY_SUMMARY_OUTPUT_SCHEMA
                ),
            }
            output_schema = schemas.get(prompt_id)
            if output_schema is None:
                raise ValueError(f"unsupported Review Prompt slot: {prompt_id}")
            prompt_ref = self._prompt_refs.get(prompt_id)
            if prompt_ref is None:
                # Runtime lookup is intentionally lazy: a DRAFT slot fails closed
                # at selection and never reaches StructuredInferencePort.
                prompt_ref = load_prompt_reference(prompt_id, self._prompt_manifest_path)
                self._prompt_refs[prompt_id] = prompt_ref
            result = llm_runtime.invoke_structured(
                prompt_ref=prompt_ref,
                prompt_input=prompt_input,
                output_schema=output_schema,
                trace_context=_trace_context(state, prompt_id),
            )
            if on_result is not None:
                on_result(result)
            if not isinstance(result.structured_output, Mapping):
                raise ValueError("Review structured output must be an object")
            return result.structured_output

        return invoke


def _trace_context(state: Mapping[str, object], prompt_id: str) -> ObservabilityContext:
    run_id = str(state.get("run_id", "review"))
    return ObservabilityContext(
        request_id=str(state.get("request_id", run_id)),
        command_id=str(state.get("command_id", run_id)),
        conversation_id=str(state.get("conversation_id", run_id)),
        run_id=run_id,
        langgraph_thread_id=str(state.get("workflow_key", run_id)),
        llm_call_id=f"{run_id}:{prompt_id}",
    )
