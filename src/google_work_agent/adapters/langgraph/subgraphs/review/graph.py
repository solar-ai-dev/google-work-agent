# ruff: noqa: E501
"""Canonical Review owner-local LangGraph composition and production integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
    RESUME_CONTRACT_VERSION,
)
from google_work_agent.adapters.langgraph.main.state import MultiAgentGraphStateV2
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.langgraph.subgraph_state import ReviewInputState, ReviewLocalState
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
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_aggregate_review_findings import (
    route_after_aggregate_review_findings,
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
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_recheck_affected_dimensions import (
    route_after_recheck_affected_dimensions,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewSemanticInvoker,
    review_recheck_output_schema,
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
from google_work_agent.application.orchestration.confirmation import build_user_interrupt_v1
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import ClarificationQuestionV1
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.orchestration.review_v2_signals import (
    project_review_workflow_signal_v2,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorDecisionV1,
    route_supervisor,
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

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
ConfirmInline = Callable[
    [ReviewLocalState], tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None]
]

_DIMENSIONS: tuple[ReviewDimensionIdV1, ...] = (
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
)


@dataclass(frozen=True, slots=True)
class ReviewRuntimeDependencies:
    """Infrastructure-only dependency for the single Review semantic invoker."""

    invoke: ReviewSemanticInvoker


class ReviewSubgraph:
    """The only executable Review graph: five runtime nodes, no pseudo validator node."""

    def __init__(
        self,
        *,
        dependencies: ReviewRuntimeDependencies | None = None,
        llm_runtime: StructuredLLMRuntime | None = None,
        prompt_manifest_path: Path | None = None,
        id_factory: Callable[[], str] | None = None,
        graph_profile: GraphProfile | None = None,
        merge_decision: MergeDecision | None = None,
        evidence_store: RunScopedEvidenceStore | None = None,
        confirm_inline: ConfirmInline | None = None,
        resume_target_registry: ResumeTargetRegistry | None = None,
    ) -> None:
        if dependencies is not None and llm_runtime is not None:
            raise ValueError("supply either ReviewRuntimeDependencies or llm_runtime")
        self._dependencies = dependencies
        self._llm_runtime = llm_runtime
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline
        self._resume_target_registry = resume_target_registry
        self._prompt_manifest_path = prompt_manifest_path or default_prompt_manifest_path()
        self._prompt_refs: dict[str, PromptReference] = {}

    @property
    def _is_production_integration(self) -> bool:
        return all(
            value is not None
            for value in (
                self._llm_runtime,
                self._id_factory,
                self._graph_profile,
                self._merge_decision,
                self._evidence_store,
                self._confirm_inline,
                self._resume_target_registry,
            )
        )

    def build(self) -> Any:
        graph = (
            StateGraph(
                ReviewLocalState,
                input_schema=ReviewInputState,
                output_schema=MultiAgentGraphStateV2,
            )
            if self._is_production_integration
            else StateGraph(ReviewLocalState)
        )
        graph.add_node("inspect_goal_and_evidence", self._inspect_goal_and_evidence_node)
        graph.add_node("inspect_action_scope_route", self._inspect_action_scope_and_route_node)
        graph.add_node(
            "inspect_constraints_policy", self._inspect_constraints_and_policy_summary_node
        )
        graph.add_node("aggregate_findings", self._aggregate_review_findings_node)
        graph.add_node("recheck", self._recheck_affected_dimensions_node)
        graph.add_conditional_edges(
            START,
            self._route_at_entry,
            {
                "inspect_goal_and_evidence": "inspect_goal_and_evidence",
                "recheck": "recheck",
                "end": END,
            },
        )
        graph.add_conditional_edges(
            "inspect_goal_and_evidence",
            route_after_inspect_goal_and_evidence,
            {
                "inspect_action_scope_route": "inspect_action_scope_route",
                "inspect_constraints_policy": "inspect_constraints_policy",
                "aggregate_findings": "aggregate_findings",
            },
        )
        graph.add_conditional_edges(
            "inspect_action_scope_route",
            route_after_inspect_action_scope_and_route,
            {
                "inspect_constraints_policy": "inspect_constraints_policy",
                "aggregate_findings": "aggregate_findings",
            },
        )
        graph.add_conditional_edges(
            "inspect_constraints_policy",
            route_after_inspect_constraints_and_policy_summary,
            {"aggregate_findings": "aggregate_findings"},
        )
        graph.add_conditional_edges(
            "recheck",
            route_after_recheck_affected_dimensions,
            {"aggregate_findings": "aggregate_findings", "end": END},
        )
        graph.add_conditional_edges(
            "aggregate_findings", route_after_aggregate_review_findings, {"end": END}
        )
        return graph.compile(name="review_subgraph")

    def _route_at_entry(self, state: ReviewLocalState) -> str:
        prior = state.get("plan_review")
        context = state.get("prompt_context")
        is_recheck = isinstance(prior, Mapping) and (
            prior.get("status") == "REVISE"
            or (
                prior.get("status") == "CONFIRM"
                and (
                    isinstance(state.get("user_interrupt"), Mapping)
                    or (
                        isinstance(context, Mapping)
                        and isinstance(context.get("confirmation_response"), Mapping)
                    )
                )
            )
        )
        phase = "RECHECK" if is_recheck else state.get("review_phase", "INITIAL")
        return route_after_entry({"review_phase": phase})

    def _inspect_goal_and_evidence_node(self, state: ReviewLocalState) -> ReviewLocalState:
        working = self._project_runtime_inputs(state)
        return self._run_semantic_node(
            state,
            working,
            "inspect_goal_and_evidence",
            lambda invoke: inspect_goal_and_evidence_node(working, invoke=invoke),
        )

    def _inspect_action_scope_and_route_node(self, state: ReviewLocalState) -> ReviewLocalState:
        return self._run_semantic_node(
            state,
            state,
            "inspect_action_scope_route",
            lambda invoke: inspect_action_scope_and_route_node(state, invoke=invoke),
        )

    def _inspect_constraints_and_policy_summary_node(
        self, state: ReviewLocalState
    ) -> ReviewLocalState:
        return self._run_semantic_node(
            state,
            state,
            "inspect_constraints_policy",
            lambda invoke: inspect_constraints_and_policy_summary_node(state, invoke=invoke),
        )

    def _recheck_affected_dimensions_node(self, state: ReviewLocalState) -> ReviewLocalState:
        working = self._project_runtime_inputs(state)
        if working.get("__target__") == "end":
            return working
        return self._run_semantic_node(
            state,
            working,
            "recheck",
            lambda invoke: recheck_affected_dimensions_node(working, invoke=invoke),
        )

    def _aggregate_review_findings_node(self, state: ReviewLocalState) -> ReviewLocalState:
        patch = aggregate_review_findings_node(state)
        if not self._is_production_integration:
            return cast(ReviewLocalState, patch)
        result = cast(PlanReviewResultV2, patch["review_result"])
        signal = self._signal(result)
        assert self._merge_decision is not None
        decision = route_supervisor(
            phase=WorkflowPhase.PLAN_REVIEW,
            state=cast(MultiAgentGraphState, {**state, "plan_review": result}),
            result=result,
        )
        decision_update = dict(decision["state_update"])
        prompt_context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        prompt_context["review_affected_dimensions"] = self._affected_dimensions_from_findings(
            cast(Sequence[Mapping[str, object]], patch["prior_review_findings"])
        )
        prompt_context["review_prior_findings"] = [
            dict(finding)
            for finding in cast(Sequence[Mapping[str, object]], patch["prior_review_findings"])
        ]
        if signal is not None:
            decision_update["workflow_signal"] = signal
        if result["status"] == "CONFIRM":
            interrupt_id = cast(str, cast(Mapping[str, object], signal)["interrupt_id"])
            decision_update["user_interrupt"] = {
                **build_user_interrupt_v1(self._clarification(result)),
                "interrupt_id": interrupt_id,
            }
            prompt_context["confirmation_interrupt"] = {
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "semantic_owner_id": "REVIEW",
                "origin_target": "review.aggregate_findings",
            }
        else:
            prompt_context.pop("confirmation_interrupt", None)
        decision_update["prompt_context"] = prompt_context
        decision = cast(
            SupervisorDecisionV1,
            {**decision, "state_update": cast(GraphStateUpdateV1, decision_update)},
        )
        merged = self._merge_decision(
            state,
            cast(GraphStateUpdateV1, {**patch, "plan_review": result}),
            decision,
        )
        return cast(ReviewLocalState, merged)

    def _run_semantic_node(
        self,
        original: ReviewLocalState,
        working: Mapping[str, object],
        node_name: str,
        operation: Callable[[ReviewSemanticInvoker], Mapping[str, object]],
    ) -> ReviewLocalState:
        results: list[StructuredLLMResult] = []
        if self._is_production_integration:
            ensure_llm_call_budget(cast(Any, original))
        patch = operation(self.semantic_invoker(working, on_result=results.append))
        result = cast(ReviewLocalState, {**working, **patch})
        if self._is_production_integration:
            consumed = sum(item.structured_output_attempts for item in results)
            result["retry_budget"] = consume_llm_call_budget(
                cast(Any, original), provider_calls_consumed=consumed
            )
            assert self._graph_profile is not None
            result["trace_context"] = merge_trace_context(
                original,
                graph_profile=self._graph_profile.value,
                agent_subgraph_id="review",
                agent_role="review",
                agent_invocation_id=str(original.get("run_id", "review")),
                subgraph_namespace="review",
                node_name=node_name,
                llm_call_id=f"{original.get('run_id', 'review')}:review.{node_name}",
                agent_invocation_increment=(
                    1 if node_name in {"inspect_goal_and_evidence", "recheck"} else 0
                ),
                llm_call_increment=consumed,
                repair_increment=sum(
                    max(0, item.structured_output_attempts - 1) for item in results
                ),
            )
        return result

    def _project_runtime_inputs(self, state: ReviewLocalState) -> ReviewLocalState:
        working = cast(ReviewLocalState, dict(state))
        if not self._is_production_integration:
            return working
        prior = state.get("plan_review")
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        if (
            isinstance(state.get("user_interrupt"), Mapping)
            and "confirmation_response" not in context
        ):
            assert self._confirm_inline is not None
            confirmation_response, early = self._confirm_inline(state)
            if early is not None:
                return cast(ReviewLocalState, {**working, **early})
            if confirmation_response is None:
                raise ValueError("Review confirmation response is required")
            context["confirmation_response"] = dict(confirmation_response)
            working["user_interrupt"] = None
        raw_response = context.get("confirmation_response")
        if isinstance(raw_response, Mapping):
            working["confirmation_response"] = dict(raw_response)
        working["prompt_context"] = context
        raw_planning_result: object = state.get("planning_result")
        if not isinstance(raw_planning_result, Mapping):
            raw_planning_result = state.get("plan_draft") or state.get("answer_draft")
        if not isinstance(raw_planning_result, Mapping):
            raise ValueError("Review requires a validated Planning artifact")
        planning_result = cast(Mapping[str, object], raw_planning_result)
        working["planning_result"] = cast(Any, dict(planning_result))
        if "work_analysis" not in working and isinstance(
            state.get("work_analysis_result"), Mapping
        ):
            working["work_analysis"] = dict(
                cast(Mapping[str, object], state["work_analysis_result"])
            )
        working["evidence"] = self._evidence(state)
        if not isinstance(working.get("policy_summary"), Mapping):
            working["policy_summary"] = {}
        prior_meta = prior.get("meta") if isinstance(prior, Mapping) else None
        is_recheck = isinstance(prior, Mapping) and (
            prior.get("status") == "REVISE" or isinstance(raw_response, Mapping)
        )
        working["review_phase"] = "RECHECK" if is_recheck else "INITIAL"
        if isinstance(prior_meta, Mapping):
            working["review_artifact_id"] = cast(str, prior_meta["artifact_id"])
            working["review_revision"] = int(prior_meta["revision"]) + 1
        else:
            assert self._id_factory is not None
            working["review_artifact_id"] = self._id_factory()
            working["review_revision"] = 1
        working["review_based_on"] = self._based_on(planning_result)
        if is_recheck:
            findings = self._findings_from_result(cast(PlanReviewResultV2, prior))
            stored_findings = context.get("review_prior_findings")
            if not findings and isinstance(stored_findings, list):
                findings = [
                    dict(finding) for finding in stored_findings if isinstance(finding, Mapping)
                ]
            working["prior_review_findings"] = findings
            working["affected_dimensions"] = self._affected_dimensions_from_result(
                cast(PlanReviewResultV2, prior), context
            )
            working["affected_action_ids"] = self._affected_ids(findings, "affected_action_ids")
            working["affected_route_ids"] = self._affected_ids(findings, "affected_route_ids")
        return working

    def _evidence(self, state: ReviewLocalState) -> list[Any]:
        direct = state.get("evidence")
        if isinstance(direct, list):
            return list(direct)
        retrieval = state.get("retrieval_result")
        if retrieval is None:
            return []
        assert self._evidence_store is not None
        return list(
            resolve_evidence_projection(
                store=self._evidence_store,
                run_id=cast(str, state["run_id"]),
                retrieval_result=cast(Any, retrieval),
            )
        )

    @staticmethod
    def _based_on(planning_result: Mapping[str, object]) -> list[dict[str, object]]:
        meta = planning_result.get("meta")
        if not isinstance(meta, Mapping):
            return []
        artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
        return (
            [{"artifact_id": artifact_id, "revision": revision}]
            if isinstance(artifact_id, str) and isinstance(revision, int)
            else []
        )

    def _signal(self, result: PlanReviewResultV2) -> Any:
        if result["status"] != "CONFIRM":
            return project_review_workflow_signal_v2(result)
        assert (
            self._id_factory is not None
            and self._resume_target_registry is not None
            and self._graph_profile is not None
        )
        target = self._resume_target_registry.issue_agent_node(
            self._graph_profile.value,
            "REVIEW",
            "review.aggregate_findings",
            RESUME_CONTRACT_VERSION,
        )
        return project_review_workflow_signal_v2(
            result, interrupt_id=self._id_factory(), resume_target=target
        )

    @staticmethod
    def _clarification(result: PlanReviewResultV2) -> ClarificationQuestionV1:
        if result["status"] != "CONFIRM":
            raise ValueError("Review clarification requires CONFIRM")
        confirmation = result["confirmation"]
        return {
            "schema_version": 1,
            "origin_target": "review.aggregate_findings",
            "question": confirmation["question"],
            "affected_field_paths": [],
            "reason_code": "PLAN_REVIEW_CONFIRM",
            "known_context_summary": "Review requires user confirmation.",
            "options": [
                {"option_id": option, "label": option} for option in confirmation["options"]
            ],
        }

    @staticmethod
    def _affected_dimensions_from_findings(findings: Sequence[Mapping[str, object]]) -> list[str]:
        requested = {item.get("dimension") for item in findings}
        return [dimension for dimension in _DIMENSIONS if dimension in requested]

    @classmethod
    def _affected_dimensions_from_result(
        cls, result: PlanReviewResultV2, context: Mapping[str, object]
    ) -> list[str]:
        if result["status"] == "REVISE":
            requested = {
                dimension
                for issue in result["issues"]
                for dimension in issue["affected_dimensions"]
            }
            return [dimension for dimension in _DIMENSIONS if dimension in requested]
        stored = context.get("review_affected_dimensions")
        if isinstance(stored, list):
            selected: list[str] = [
                dimension for dimension in _DIMENSIONS if dimension in set(stored)
            ]
            if selected:
                return selected
        raise ValueError("Review recheck requires persisted affected dimensions")

    @staticmethod
    def _findings_from_result(result: PlanReviewResultV2) -> list[dict[str, object]]:
        if result["status"] != "REVISE":
            return []
        return [
            {
                "dimension": dimension,
                "code": issue["code"],
                "finding_kind": "ISSUE",
                "description": issue["description"],
                "evidence_refs": list(issue["evidence_refs"]),
                "affected_action_ids": list(issue["affected_action_ids"]),
                "affected_route_ids": list(issue["affected_route_ids"]),
                "required_information": [],
            }
            for issue in result["issues"]
            for dimension in issue["affected_dimensions"]
        ]

    @staticmethod
    def _affected_ids(findings: Sequence[Mapping[str, object]], key: str) -> list[str]:
        return list(
            dict.fromkeys(
                value for finding in findings for value in cast(Sequence[str], finding.get(key, ()))
            )
        )

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

        def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
            schemas: dict[str, OutputSchemaDefinition] = {
                "review.inspect_goal_and_evidence": REVIEW_INSPECT_GOAL_AND_EVIDENCE_OUTPUT_SCHEMA,
                "review.inspect_action_scope_and_route": REVIEW_INSPECT_ACTION_SCOPE_AND_ROUTE_OUTPUT_SCHEMA,
                "review.inspect_constraints_and_policy_summary": REVIEW_INSPECT_CONSTRAINTS_AND_POLICY_SUMMARY_OUTPUT_SCHEMA,
            }
            output_schema = schemas.get(prompt_id)
            if prompt_id == "review.recheck_affected_dimensions":
                raw_dimensions = prompt_input.get("affected_dimensions")
                if not isinstance(raw_dimensions, list):
                    raise ValueError("Review recheck affected_dimensions are required")
                output_schema = review_recheck_output_schema(
                    cast(tuple[ReviewDimensionIdV1, ...], tuple(raw_dimensions))
                )
            if output_schema is None:
                raise ValueError(f"unsupported Review Prompt slot: {prompt_id}")
            prompt_ref = self._prompt_refs.get(prompt_id)
            if prompt_ref is None:
                prompt_ref = load_prompt_reference(prompt_id, self._prompt_manifest_path)
                self._prompt_refs[prompt_id] = prompt_ref
            llm_runtime = self._llm_runtime
            if llm_runtime is None:
                raise RuntimeError("Review semantic runtime dependency is required")
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


__all__ = ["ReviewRuntimeDependencies", "ReviewSubgraph"]
