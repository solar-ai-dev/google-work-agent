"""Canonical Work Analysis runtime for the #115 atomic relation slice."""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.agent_kernel import (
    build_agent_local_state,
    consume_llm_call_budget,
    ensure_llm_call_budget,
    merge_trace_context,
)
from google_work_agent.adapters.langgraph.main.state import (
    ANALYSIS_AGENT_LOCAL_KEY,
    ParentGraphState,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraph_state import (
    WorkAnalysisInputState,
    WorkAnalysisLocalState,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.detect_duplicate_conflict_candidates_node import (
    detect_duplicate_conflict_candidates_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.extract_work_facts_node import (
    extract_work_facts_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.resolve_entity_relations_node import (
    resolve_entity_relations_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.resolve_temporal_dependencies_node import (
    resolve_temporal_dependencies_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.nodes.validate_relations_node import (
    validate_relations_node,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_detect_duplicate_conflict_candidates import (
    route_after_detect_duplicate_conflict_candidates,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_extract_work_facts import (
    route_after_extract_work_facts,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_resolve_entity_relations import (
    route_after_resolve_entity_relations,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_resolve_temporal_dependencies import (
    route_after_resolve_temporal_dependencies,
)
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.routing.route_after_validate_relations import (
    route_after_validate_relations,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
)
from google_work_agent.application.orchestration.confirmation import build_user_interrupt_v1
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseProjectionV1,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    WorkflowPhase,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    ClarificationQuestionV1,
    EvidenceDraftV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
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
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [WorkAnalysisLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class WorkAnalysisSubgraph:
    """Run the four atomic Prompt operations and deterministic relation authority."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_manifest_path: Path | None,
        id_factory: Callable[[], str],
        graph_profile: GraphProfile,
        transition_run: TransitionRun,
        merge_decision: MergeDecision,
        evidence_store: RunScopedEvidenceStore,
        confirm_inline: ConfirmInline,
    ) -> None:
        self._llm_runtime = llm_runtime
        manifest = prompt_manifest_path or default_prompt_manifest_path()
        self._prompt_refs = {
            "extract_work_facts": load_prompt_reference(
                "work_analysis.extract_work_facts", manifest
            ),
            "resolve_entity_relations": load_prompt_reference(
                "work_analysis.resolve_entity_relations", manifest
            ),
            "resolve_temporal_dependencies": load_prompt_reference(
                "work_analysis.resolve_temporal_dependencies", manifest
            ),
            "detect_duplicate_conflict_candidates": load_prompt_reference(
                "work_analysis.detect_duplicate_conflict_candidates", manifest
            ),
        }
        self._id_factory = id_factory
        self._graph_profile = graph_profile
        self._transition_run = transition_run
        self._merge_decision = merge_decision
        self._evidence_store = evidence_store
        self._confirm_inline = confirm_inline

    def build(self) -> Any:
        graph = StateGraph(
            WorkAnalysisLocalState,
            input_schema=WorkAnalysisInputState,
            output_schema=ParentGraphState,
        )
        graph.add_node("extract_work_facts", self._extract_work_facts_node)
        graph.add_node("resolve_entity_relations", self._resolve_entity_relations_node)
        graph.add_node("resolve_temporal_dependencies", self._resolve_temporal_dependencies_node)
        graph.add_node(
            "detect_duplicate_conflict_candidates", self._detect_duplicate_conflict_candidates_node
        )
        graph.add_node("validate_relations", self._validate_relations_node)
        graph.add_node("compatibility_projection", self._compatibility_projection_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "extract_work_facts")
        graph.add_conditional_edges(
            "extract_work_facts",
            route_after_extract_work_facts,
            {"resolve_entity_relations": "resolve_entity_relations"},
        )
        graph.add_conditional_edges(
            "resolve_entity_relations",
            route_after_resolve_entity_relations,
            {"resolve_temporal_dependencies": "resolve_temporal_dependencies"},
        )
        graph.add_conditional_edges(
            "resolve_temporal_dependencies",
            route_after_resolve_temporal_dependencies,
            {"detect_duplicate_conflict_candidates": "detect_duplicate_conflict_candidates"},
        )
        graph.add_conditional_edges(
            "detect_duplicate_conflict_candidates",
            route_after_detect_duplicate_conflict_candidates,
            {"validate_relations": "validate_relations"},
        )
        graph.add_conditional_edges(
            "validate_relations",
            route_after_validate_relations,
            {"compatibility_projection": "compatibility_projection"},
        )
        graph.add_edge("compatibility_projection", "finalize")
        graph.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"finalize": "finalize", "end": END},
        )
        return graph.compile(name="work_analysis_subgraph")

    def _extract_work_facts_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        request = request_from_state(state)
        first = not self._has_invocation(state)
        invocation_id = self._id_factory() if first else self._invocation_id(state)
        if first:
            self._transition_run(request.run_id, "begin_planning")
        retrieval_result = state.get("retrieval_result")
        evidence = self._evidence(state)
        evidence_refs = [] if retrieval_result is None else list(retrieval_result["evidence_refs"])
        working = cast(
            WorkAnalysisLocalState,
            {
                **state,
                "user_request": request.request_text,
                "request_intent": _require_state_value(
                    state.get("request_intent"), "request_intent"
                ),
                "evidence": evidence,
                "evidence_refs": evidence_refs,
                "availability_results": []
                if retrieval_result is None
                else list(retrieval_result["availability_results"]),
                "current_source_relations": [],
            },
        )
        confirmation_response = self._confirmation_response(state)
        if confirmation_response is not None:
            working["confirmation_response"] = confirmation_response
        ensure_llm_call_budget(working)
        patch = extract_work_facts_node(
            cast(Any, working),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["extract_work_facts"],
            trace_context=self._llm_trace(working, "extract_facts"),
        )
        owner_inputs = {
            "user_request": working["user_request"],
            "request_intent": working["request_intent"],
            "evidence": working["evidence"],
            "evidence_refs": working["evidence_refs"],
            "availability_results": working["availability_results"],
            "current_source_relations": working["current_source_relations"],
        }
        if confirmation_response is not None:
            owner_inputs["confirmation_response"] = confirmation_response
        if first:
            local_state = build_agent_local_state(
                agent_role="work_analysis",
                invocation_id=invocation_id,
                node_state="ATOMIC_RELATION_SLICE",
                input_projection={
                    "request_intent": working["request_intent"],
                    "retrieval_result": retrieval_result,
                },
                prompt_ref=self._prompt_refs["extract_work_facts"],
            )
            owner_inputs[ANALYSIS_AGENT_LOCAL_KEY] = local_state
            working[ANALYSIS_AGENT_LOCAL_KEY] = local_state
        return cast(
            WorkAnalysisLocalState,
            {
                **owner_inputs,
                **patch,
                "retry_budget": consume_llm_call_budget(working),
                "trace_context": self._trace(
                    working, "extract_facts", self._prompt_refs["extract_work_facts"], first
                ),
            },
        )

    def _resolve_entity_relations_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        ensure_llm_call_budget(state)
        patch = resolve_entity_relations_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["resolve_entity_relations"],
            trace_context=self._llm_trace(state, "resolve_entity_relations"),
            confirmation_response=self._confirmation_response(state),
        )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": consume_llm_call_budget(state),
                "trace_context": self._trace(
                    state, "resolve_entity_relations", self._prompt_refs["resolve_entity_relations"]
                ),
            },
        )

    def _resolve_temporal_dependencies_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        ensure_llm_call_budget(state)
        patch = resolve_temporal_dependencies_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["resolve_temporal_dependencies"],
            trace_context=self._llm_trace(state, "resolve_temporal_dependencies"),
            confirmation_response=self._confirmation_response(state),
        )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": consume_llm_call_budget(state),
                "trace_context": self._trace(
                    state,
                    "resolve_temporal_dependencies",
                    self._prompt_refs["resolve_temporal_dependencies"],
                ),
            },
        )

    def _detect_duplicate_conflict_candidates_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        ensure_llm_call_budget(state)
        patch = detect_duplicate_conflict_candidates_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["detect_duplicate_conflict_candidates"],
            trace_context=self._llm_trace(state, "detect_duplicate_conflict_candidates"),
            confirmation_response=self._confirmation_response(state),
        )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": consume_llm_call_budget(state),
                "trace_context": self._trace(
                    state,
                    "detect_duplicate_conflict_candidates",
                    self._prompt_refs["detect_duplicate_conflict_candidates"],
                ),
            },
        )

    def _validate_relations_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        patch = validate_relations_node(cast(Any, state))
        return cast(
            WorkAnalysisLocalState,
            {**patch, "trace_context": self._trace(state, "validate_relations")},
        )

    def _compatibility_projection_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        result = _project_legacy_parent_result(
            facts=cast(list[WorkFactV1], state.get("fact_candidates", [])),
            relations=cast(list[WorkRelationV1], state.get("validated_relations", [])),
            ambiguities=cast(
                list[WorkAmbiguityV1], state.get("relation_validation_ambiguities", [])
            ),
            evidence=cast(list[EvidenceDraftV1], state.get("evidence", [])),
        )
        patch: WorkAnalysisLocalState = {
            "analysis_result": result,
            "trace_context": self._trace(state, "compatibility_projection"),
        }
        if result["status"] == "NEEDS_CONFIRMATION":
            question = _clarification_question(result)
            interrupt_id = self._id_factory()
            patch["workflow_phase"] = WorkflowPhase.WAITING_CONFIRMATION.value
            patch["user_interrupt"] = cast(
                Any, {**build_user_interrupt_v1(question), "interrupt_id": interrupt_id}
            )
            patch["prompt_context"] = {
                **cast(dict[str, object], state.get("prompt_context", {})),
                "confirmation_interrupt": {
                    "schema_version": 1,
                    "interrupt_id": interrupt_id,
                    "semantic_owner_id": "WORK_ANALYSIS",
                    "origin_target": question["origin_target"],
                },
            }
        return patch

    def _finalize_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        result = _require_state_value(state.get("analysis_result"), "analysis_result")
        if result["status"] == "NEEDS_CONFIRMATION":
            response, early = self._confirm_inline(state)
            if early is not None:
                return cast(
                    WorkAnalysisLocalState, {**early, "__work_analysis_retry_confirmation__": False}
                )
            if response is None:
                raise ValueError("Work Analysis confirmation response is required")
            context = dict(cast(dict[str, object], state.get("prompt_context", {})))
            context.pop("confirmation_interrupt", None)
            context["confirmation_response"] = dict(response)
            acknowledged = [
                {**item, "requires_confirmation": False}
                for item in cast(
                    list[WorkAmbiguityV1], state.get("relation_validation_ambiguities", [])
                )
            ]
            completed = _project_legacy_parent_result(
                facts=cast(list[WorkFactV1], state.get("fact_candidates", [])),
                relations=cast(list[WorkRelationV1], state.get("validated_relations", [])),
                ambiguities=cast(list[WorkAmbiguityV1], acknowledged),
                evidence=cast(list[EvidenceDraftV1], state.get("evidence", [])),
            )
            return {
                "analysis_result": completed,
                "relation_validation_ambiguities": acknowledged,
                "user_interrupt": None,
                "prompt_context": context,
                "__work_analysis_retry_confirmation__": True,
                "trace_context": self._trace(state, "finalize"),
            }
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(MultiAgentGraphState, state),
            result=result,
        )
        merged = self._merge_decision(
            state,
            {
                "analysis_result": result,
                "workflow_phase": WorkflowPhase.SOLUTION_PLANNING.value,
                "trace_context": {
                    "analysis_result": result["status"],
                    "finding_count": len(result["findings"]),
                },
            },
            decision,
        )
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return cast(
            WorkAnalysisLocalState, {**merged, "__work_analysis_retry_confirmation__": False}
        )

    @staticmethod
    def _route_after_finalize(state: WorkAnalysisLocalState) -> str:
        return "finalize" if state.get("__work_analysis_retry_confirmation__") else "end"

    def _evidence(self, state: WorkAnalysisLocalState) -> list[EvidenceDraftV1]:
        retrieval_result = state.get("retrieval_result")
        if retrieval_result is None:
            return []
        return resolve_evidence_projection(
            store=self._evidence_store, run_id=state["run_id"], retrieval_result=retrieval_result
        )

    @staticmethod
    def _confirmation_response(state: WorkAnalysisLocalState) -> dict[str, object] | None:
        context = state.get("prompt_context", {})
        value = context.get("confirmation_response") if isinstance(context, Mapping) else None
        return dict(value) if isinstance(value, Mapping) else None

    def _llm_trace(self, state: WorkAnalysisLocalState, node: str) -> ObservabilityContext:
        request = request_from_state(state)
        return ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:analysis.{node}",
        )

    def _trace(
        self,
        state: WorkAnalysisLocalState,
        node: str,
        prompt_ref: PromptReference | None = None,
        first: bool = False,
    ) -> dict[str, object]:
        return merge_trace_context(
            state,
            graph_profile=self._graph_profile.value,
            agent_subgraph_id="work_analysis",
            agent_role="work_analysis",
            agent_invocation_id=self._invocation_id(state),
            subgraph_namespace="analysis",
            node_name=node,
            llm_call_id=(f"{state['run_id']}:analysis.{node}" if prompt_ref else None),
            prompt_ref=prompt_ref,
            agent_invocation_increment=1 if first else 0,
            llm_call_increment=1 if prompt_ref else 0,
        )

    def _invocation_id(self, state: WorkAnalysisLocalState) -> str:
        local_state = state.get(ANALYSIS_AGENT_LOCAL_KEY)
        if isinstance(local_state, Mapping):
            value = local_state.get("invocation_id")
            if isinstance(value, str) and value:
                return value
        log = state.get("trace_context", {}).get("agent_node_log", [])
        if isinstance(log, list):
            for item in reversed(log):
                if isinstance(item, Mapping) and item.get("agent_subgraph_id") == "work_analysis":
                    value = item.get("agent_invocation_id")
                    if isinstance(value, str) and value:
                        return value
        return self._id_factory()

    @staticmethod
    def _has_invocation(state: WorkAnalysisLocalState) -> bool:
        return isinstance(state.get(ANALYSIS_AGENT_LOCAL_KEY), Mapping)


def _project_legacy_parent_result(
    *,
    facts: list[WorkFactV1],
    relations: list[WorkRelationV1],
    ambiguities: list[WorkAmbiguityV1],
    evidence: list[EvidenceDraftV1],
) -> WorkAnalysisResultV1:
    by_id = {item["evidence_id"]: item for item in evidence}
    findings: list[dict[str, object]] = []
    for fact in facts:
        selected = [by_id[ref] for ref in fact["evidence_refs"] if ref in by_id]
        resource_handles = list(dict.fromkeys(item["resource_handle"] for item in selected))
        findings.append(
            {
                "schema_version": 1,
                "finding_id": fact["fact_id"],
                "kind": "FACT",
                "statement": f"{fact['subject']}: {fact['value']}",
                "evidence_refs": list(fact["evidence_refs"]),
                "resource_refs": resource_handles,
                "segment_refs": list(dict.fromkeys(item["segment_id"] for item in selected)),
                "related_resource_handles": resource_handles,
                "reason_codes": [],
            }
        )
    facts_by_id = {fact["fact_id"]: fact for fact in facts}
    for relation in relations:
        source = facts_by_id[relation["source_fact_id"]]
        target = facts_by_id[relation["target_fact_id"]]
        selected = [by_id[ref] for ref in relation["evidence_refs"] if ref in by_id]
        resource_handles = list(dict.fromkeys(item["resource_handle"] for item in selected))
        kind = (
            "CONFLICT"
            if relation["kind"] == "CONFLICTS_WITH"
            else ("DUPLICATE_CANDIDATE" if relation["kind"] == "DUPLICATES" else "RELATIONSHIP")
        )
        findings.append(
            {
                "schema_version": 1,
                "finding_id": relation["relation_id"],
                "kind": kind,
                "statement": f"{source['subject']} {relation['kind']} {target['subject']}",
                "evidence_refs": list(relation["evidence_refs"]),
                "resource_refs": resource_handles,
                "segment_refs": list(dict.fromkeys(item["segment_id"] for item in selected)),
                "related_resource_handles": resource_handles,
                "reason_codes": [],
            }
        )
    requiring = [item for item in ambiguities if item["requires_confirmation"]]
    refs = list(dict.fromkeys(ref for fact in facts for ref in fact["evidence_refs"]))
    return cast(
        WorkAnalysisResultV1,
        {
            "schema_version": 1,
            "status": "NEEDS_CONFIRMATION" if requiring else "COMPLETE",
            "summary": f"Validated {len(facts)} work facts and {len(relations)} relations.",
            "findings": findings,
            "missing_information": [item["description"] for item in ambiguities],
            "confirmation": (
                None
                if not requiring
                else {
                    "question": requiring[0]["description"],
                    "reason_code": requiring[0]["code"],
                    "affected_field_paths": [],
                    "options": [],
                }
            ),
            "blockers": [],
            "evidence_refs": refs,
            "resource_refs": [
                _resource_ref_from_handle(item["resource_handle"]) for item in evidence
            ],
            "segment_refs": [
                {
                    "segment_id": item["segment_id"],
                    "resource_handle": item["resource_handle"],
                }
                for item in evidence
            ],
            "additional_acquisition_request": None,
        },
    )


def _resource_ref_from_handle(handle: str) -> dict[str, str]:
    resource_type, separator, resource_id = handle.partition(":")
    if not separator or not resource_type or not resource_id:
        return {"resource_handle": handle}
    return {
        "resource_handle": handle,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }


def _clarification_question(result: WorkAnalysisResultV1) -> ClarificationQuestionV1:
    confirmation = cast(dict[str, object], result["confirmation"])
    return {
        "schema_version": 1,
        "origin_target": "analysis.validate_relations",
        "question": cast(str, confirmation["question"]),
        "affected_field_paths": [],
        "reason_code": cast(str, confirmation["reason_code"]),
        "known_context_summary": result["summary"],
        "options": [],
    }


__all__ = ["WorkAnalysisSubgraph"]
