"""Canonical eight-node Work Analysis production runtime."""

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
from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    build_user_interrupt_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    ANALYSIS_AGENT_LOCAL_KEY,
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
    _require_state_value,
    request_from_state,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    WorkAnalysisRouteResultV1,
    route_supervisor,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisInputState,
    WorkAnalysisLocalState,
)
from google_work_agent.adapters.system.memory.retrieval_evidence_store import (
    RunScopedEvidenceStore,
    resolve_evidence_projection,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output as request_understanding_contracts,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
)
from google_work_agent.application.agents.work_analysis import (
    detect_duplicate_conflict_candidates as duplicate_candidates,
)
from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    required_override_confirmation_kind,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    StateArtifactRefV1,
    WorkAnalysisResultV2,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    PRODUCT_RELEASE,
    PromptExecutionScope,
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import PromptReference
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
)

from .nodes.assemble_work_analysis_node import assemble_work_analysis_node
from .nodes.assess_information_gaps_node import assess_information_gaps_node
from .nodes.assess_operational_risks_node import assess_operational_risks_node
from .nodes.detect_duplicate_conflict_candidates_node import (
    detect_duplicate_conflict_candidates_node,
)
from .nodes.extract_work_facts_node import extract_work_facts_node
from .nodes.resolve_entity_relations_node import resolve_entity_relations_node
from .nodes.resolve_temporal_dependencies_node import resolve_temporal_dependencies_node
from .nodes.validate_relations_node import validate_relations_node
from .routing.route_after_assemble_work_analysis import route_after_assemble_work_analysis
from .routing.route_after_assess_information_gaps import route_after_assess_information_gaps
from .routing.route_after_assess_operational_risks import route_after_assess_operational_risks
from .routing.route_after_detect_duplicate_conflict_candidates import (
    route_after_detect_duplicate_conflict_candidates,
)
from .routing.route_after_extract_work_facts import route_after_extract_work_facts
from .routing.route_after_resolve_entity_relations import route_after_resolve_entity_relations
from .routing.route_after_resolve_temporal_dependencies import (
    route_after_resolve_temporal_dependencies,
)
from .routing.route_after_validate_relations import route_after_validate_relations

MergeDecision = Callable[[Any, GraphStateUpdateV1, SupervisorDecisionV1], Any]
TransitionRun = Callable[[str, str], None]
ConfirmInline = Callable[
    [WorkAnalysisLocalState],
    tuple[ConfirmationResponseProjectionV1 | None, dict[str, object] | None],
]


class WorkAnalysisSubgraph:
    """Run six atomic Prompt operations and two deterministic runtime nodes."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredInferencePort,
        prompt_manifest_path: Path | None,
        prompt_execution_scope: PromptExecutionScope = PRODUCT_RELEASE,
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
                "work_analysis.extract_work_facts",
                manifest,
                execution_scope=prompt_execution_scope,
            ),
            "resolve_entity_relations": load_prompt_reference(
                "work_analysis.resolve_entity_relations",
                manifest,
                execution_scope=prompt_execution_scope,
            ),
            "resolve_temporal_dependencies": load_prompt_reference(
                "work_analysis.resolve_temporal_dependencies",
                manifest,
                execution_scope=prompt_execution_scope,
            ),
            "detect_duplicate_conflict_candidates": load_prompt_reference(
                "work_analysis.detect_duplicate_conflict_candidates",
                manifest,
                execution_scope=prompt_execution_scope,
            ),
            "assess_information_gaps": load_prompt_reference(
                "work_analysis.assess_information_gaps",
                manifest,
                execution_scope=prompt_execution_scope,
            ),
            "assess_operational_risks": load_prompt_reference(
                "work_analysis.assess_operational_risks",
                manifest,
                execution_scope=prompt_execution_scope,
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
            output_schema=GraphState,
        )
        graph.add_node("extract_work_facts", self._extract_work_facts_node)
        graph.add_node("resolve_entity_relations", self._resolve_entity_relations_node)
        graph.add_node("resolve_temporal_dependencies", self._resolve_temporal_dependencies_node)
        graph.add_node(
            "detect_duplicate_conflict_candidates", self._detect_duplicate_conflict_candidates_node
        )
        graph.add_node("validate_relations", self._validate_relations_node)
        graph.add_node("assess_information_gaps", self._assess_information_gaps_node)
        graph.add_node("assess_operational_risks", self._assess_operational_risks_node)
        graph.add_node("finalize", self._finalize_node)
        graph.add_edge(START, "extract_work_facts")
        graph.add_conditional_edges(
            "extract_work_facts",
            route_after_extract_work_facts,
            {
                "resolve_entity_relations": "resolve_entity_relations",
                "resolve_temporal_dependencies": "resolve_temporal_dependencies",
                "detect_duplicate_conflict_candidates": "detect_duplicate_conflict_candidates",
                "validate_relations": "validate_relations",
            },
        )
        graph.add_conditional_edges(
            "resolve_entity_relations",
            route_after_resolve_entity_relations,
            {
                "resolve_temporal_dependencies": "resolve_temporal_dependencies",
                "detect_duplicate_conflict_candidates": "detect_duplicate_conflict_candidates",
            },
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
            {"assess_information_gaps": "assess_information_gaps"},
        )
        graph.add_conditional_edges(
            "assess_information_gaps",
            route_after_assess_information_gaps,
            {
                "assess_operational_risks": "assess_operational_risks",
                "finalize": "finalize",
            },
        )
        graph.add_conditional_edges(
            "assess_operational_risks",
            route_after_assess_operational_risks,
            {"finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "finalize",
            route_after_assemble_work_analysis,
            {
                "assess_operational_risks": "assess_operational_risks",
                "end": END,
            },
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
            requested_mode=request.requested_mode,
        )
        owner_inputs: dict[str, object] = {
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
        returned = cast(
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
        returned["entity_relation_candidates"] = []
        returned["temporal_dependency_candidates"] = []
        returned["duplicate_conflict_candidates"] = []
        return returned

    def _resolve_entity_relations_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        ensure_llm_call_budget(state)
        patch = resolve_entity_relations_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["resolve_entity_relations"],
            requested_mode=request_from_state(state).requested_mode,
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
            requested_mode=request_from_state(state).requested_mode,
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
        llm_required = duplicate_candidates.duplicate_conflict_candidate_llm_required(
            state.get("fact_candidates", [])
        )
        if llm_required:
            ensure_llm_call_budget(state)
        patch = detect_duplicate_conflict_candidates_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["detect_duplicate_conflict_candidates"],
            requested_mode=request_from_state(state).requested_mode,
            confirmation_response=self._confirmation_response(state),
        )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": (
                    consume_llm_call_budget(state) if llm_required else state["retry_budget"]
                ),
                "trace_context": self._trace(
                    state,
                    "detect_duplicate_conflict_candidates",
                    (
                        self._prompt_refs["detect_duplicate_conflict_candidates"]
                        if llm_required
                        else None
                    ),
                ),
            },
        )

    def _validate_relations_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        patch = validate_relations_node(cast(Any, state))
        return cast(
            WorkAnalysisLocalState,
            {**patch, "trace_context": self._trace(state, "validate_relations")},
        )

    def _assess_information_gaps_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        working = cast(WorkAnalysisLocalState, dict(state))
        confirmation_response = self._confirmation_response(state)
        if confirmation_response is not None:
            working["confirmation_response"] = confirmation_response
        ensure_llm_call_budget(working)
        patch = assess_information_gaps_node(
            cast(Any, working),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["assess_information_gaps"],
            requested_mode=request_from_state(state).requested_mode,
        )
        assessment = patch.get("__analysis_information_gap_assessment__")
        if (
            isinstance(assessment, Mapping)
            and assessment.get("disposition") == "NEEDS_CONFIRMATION"
        ):
            reason_codes = cast(list[str], assessment.get("reason_codes", []))
            cast(dict[str, Any], patch).update(
                self._confirmation_patch(
                    state,
                    origin_target="analysis.assess_information_gaps",
                    question=cast(str, assessment.get("question")),
                    reason_code=(
                        reason_codes[0] if reason_codes else "WORK_ANALYSIS_NEEDS_CONFIRMATION"
                    ),
                    options=[
                        {"option_id": value, "label": value}
                        for value in cast(list[str], assessment.get("options", []))
                    ],
                )
            )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": consume_llm_call_budget(working),
                "trace_context": self._trace(
                    state,
                    "assess_information_gaps",
                    self._prompt_refs["assess_information_gaps"],
                ),
            },
        )

    def _assess_operational_risks_node(
        self, state: WorkAnalysisLocalState
    ) -> WorkAnalysisLocalState:
        ensure_llm_call_budget(state)
        patch = assess_operational_risks_node(
            cast(Any, state),
            llm_runtime=self._llm_runtime,
            prompt_ref=self._prompt_refs["assess_operational_risks"],
            requested_mode=request_from_state(state).requested_mode,
        )
        assessment = patch.get("__analysis_operational_risk_assessment__")
        if isinstance(assessment, Mapping):
            override_kind = required_override_confirmation_kind(
                validated_relations=cast(list[Any], state.get("validated_relations", [])),
                action_necessity_candidate=cast(Any, assessment["action_necessity_candidate"]),
                policy_confirmation_receipts=cast(
                    list[PolicyConfirmationReceiptV1],
                    state.get("policy_confirmation_receipts", []),
                ),
                based_on=self._based_on(state),
            )
            if override_kind is not None:
                cast(dict[str, Any], patch).update(
                    self._confirmation_patch(
                        state,
                        origin_target="analysis.assess_operational_risks",
                        question=(
                            "조회한 자료에서 중복된 업무 또는 일정 충돌이 확인됐습니다. "
                            "이를 감안하여 작업 제안을 계속 준비할까요? "
                            "실제 실행은 별도로 승인받습니다."
                        ),
                        reason_code=f"{override_kind}_REQUIRED",
                        options=[
                            {"option_id": "APPROVED", "label": "계속 준비해 주세요"},
                            {"option_id": "DECLINED", "label": "진행하지 않을게요"},
                        ],
                        policy_confirmation={
                            "confirmation_kind": override_kind,
                            "based_on": self._based_on(state),
                        },
                    )
                )
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "retry_budget": consume_llm_call_budget(state),
                "trace_context": self._trace(
                    state,
                    "assess_operational_risks",
                    self._prompt_refs["assess_operational_risks"],
                ),
            },
        )

    def _finalize_node(self, state: WorkAnalysisLocalState) -> WorkAnalysisLocalState:
        gap_assessment = state.get("__analysis_information_gap_assessment__")
        if isinstance(gap_assessment, Mapping) and gap_assessment.get("disposition") != "COMPLETE":
            return self._resolve_gap_disposition(state, gap_assessment)

        risk_assessment = _require_state_value(
            state.get("__analysis_operational_risk_assessment__"),
            "operational risk assessment",
        )
        based_on = self._based_on(state)
        override_kind = required_override_confirmation_kind(
            validated_relations=cast(list[Any], state.get("validated_relations", [])),
            action_necessity_candidate=cast(Any, risk_assessment["action_necessity_candidate"]),
            policy_confirmation_receipts=cast(
                list[PolicyConfirmationReceiptV1],
                state.get("policy_confirmation_receipts", []),
            ),
            based_on=based_on,
        )
        if override_kind is not None:
            return self._resolve_confirmation(
                state,
                origin_target="analysis.assess_operational_risks",
                question=(
                    "조회한 자료에서 중복된 업무 또는 일정 충돌이 확인됐습니다. "
                    "이를 감안하여 작업 제안을 계속 준비할까요? 실제 실행은 별도로 승인받습니다."
                ),
                reason_code=f"{override_kind}_REQUIRED",
                options=[
                    {"option_id": "APPROVED", "label": "계속 준비해 주세요"},
                    {"option_id": "DECLINED", "label": "진행하지 않을게요"},
                ],
                policy_confirmation={
                    "confirmation_kind": override_kind,
                    "based_on": based_on,
                },
            )

        patch = assemble_work_analysis_node(
            cast(dict[str, object], state),
            artifact_id=self._id_factory(),
        )
        result = cast(WorkAnalysisResultV2, patch["final_analysis"])
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(GraphState, state),
            result=cast(
                WorkAnalysisRouteResultV1,
                {
                    "disposition": "COMPLETE",
                    "typed_result": result,
                    "workflow_signal": None,
                    "reason_codes": [],
                },
            ),
        )
        merged = self._merge_decision(
            state,
            {
                "work_analysis_result": result,
                "trace_context": {
                    "work_analysis_result": "COMPLETE",
                    "fact_count": len(result["work_facts"]),
                    "relation_count": len(result["relations"]),
                },
            },
            decision,
        )
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return cast(
            WorkAnalysisLocalState, {**merged, "__work_analysis_retry_confirmation__": False}
        )

    def _resolve_gap_disposition(
        self,
        state: WorkAnalysisLocalState,
        assessment: Mapping[str, object],
    ) -> WorkAnalysisLocalState:
        disposition = assessment.get("disposition")
        reason_codes = [
            item
            for item in cast(list[object], assessment.get("reason_codes", []))
            if isinstance(item, str) and item
        ] or [f"WORK_ANALYSIS_{disposition or 'BLOCKED'}"]
        if disposition == "NEEDS_CONFIRMATION":
            return self._resolve_confirmation(
                state,
                origin_target="analysis.assess_information_gaps",
                question=cast(
                    str,
                    assessment.get("question")
                    or "Please clarify the missing information required for this analysis.",
                ),
                reason_code=reason_codes[0],
                options=[
                    {"option_id": value, "label": value}
                    for value in cast(list[str], assessment.get("options", []))
                    if isinstance(value, str) and value
                ],
            )
        if disposition == "NEEDS_MORE_DATA":
            signal: RetrievalRequiredV1 | RouteReconsiderationRequiredV1
            if self._has_usable_input_route(state):
                signal = {
                    "kind": "RETRIEVAL_REQUIRED",
                    "reason_codes": reason_codes,
                    "needs": list(cast(list[Any], state.get("retrieval_needs", []))),
                }
            else:
                signal = {
                    "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                    "reason_codes": reason_codes,
                }
                disposition = "ROUTE_RECONSIDERATION_REQUIRED"
            return self._finish_with_signal(
                state,
                disposition=cast(Any, disposition),
                signal=signal,
            )
        if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            return self._finish_with_signal(
                state,
                disposition="ROUTE_RECONSIDERATION_REQUIRED",
                signal={
                    "kind": "ROUTE_RECONSIDERATION_REQUIRED",
                    "reason_codes": reason_codes,
                },
            )
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(GraphState, state),
            result=cast(
                WorkAnalysisRouteResultV1,
                {
                    "disposition": "BLOCKED",
                    "typed_result": None,
                    "workflow_signal": None,
                    "reason_codes": reason_codes,
                },
            ),
        )
        return cast(
            WorkAnalysisLocalState,
            {
                **self._merge_decision(state, {}, decision),
                "__work_analysis_retry_confirmation__": False,
            },
        )

    def _finish_with_signal(
        self,
        state: WorkAnalysisLocalState,
        *,
        disposition: str,
        signal: RetrievalRequiredV1 | RouteReconsiderationRequiredV1,
    ) -> WorkAnalysisLocalState:
        reason_codes = signal["reason_codes"]
        decision = route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=cast(GraphState, state),
            result=cast(
                WorkAnalysisRouteResultV1,
                {
                    "disposition": disposition,
                    "typed_result": None,
                    "workflow_signal": signal,
                    "reason_codes": reason_codes,
                },
            ),
        )
        merged = self._merge_decision(state, {}, decision)
        merged.pop(ANALYSIS_AGENT_LOCAL_KEY, None)
        return cast(
            WorkAnalysisLocalState,
            {**merged, "__work_analysis_retry_confirmation__": False},
        )

    def _resolve_confirmation(
        self,
        state: WorkAnalysisLocalState,
        *,
        origin_target: str,
        question: str,
        reason_code: str,
        options: list[dict[str, str]],
        policy_confirmation: dict[str, object] | None = None,
    ) -> WorkAnalysisLocalState:
        del question, reason_code, options, policy_confirmation
        working = cast(WorkAnalysisLocalState, dict(state))
        if not isinstance(working.get("user_interrupt"), Mapping):
            raise ValueError("Work Analysis confirmation must be checkpointed by its producer node")
        response, early = self._confirm_inline(working)
        if early is not None:
            return cast(
                WorkAnalysisLocalState,
                {**early, "__work_analysis_retry_confirmation__": False},
            )
        if response is None:
            raise ValueError("Work Analysis confirmation response is required")
        context = dict(cast(Mapping[str, object], working.get("prompt_context", {})))
        context.pop("confirmation_interrupt", None)
        context["confirmation_response"] = dict(response)
        patch: dict[str, Any] = {}
        if origin_target == "analysis.assess_information_gaps":
            acknowledged = [
                {**item, "requires_confirmation": False}
                for item in cast(list[dict[str, object]], working.get("ambiguity_candidates", []))
            ]
            patch.update(
                {
                    "ambiguity_candidates": cast(Any, acknowledged),
                    "relation_validation_ambiguities": cast(Any, acknowledged),
                    "__analysis_information_gap_assessment__": {
                        "disposition": "COMPLETE",
                        "ambiguities": acknowledged,
                        "retrieval_needs": [],
                        "evidence_refs": list(working.get("evidence_refs", [])),
                    },
                    "__analysis_noncomplete_disposition__": "RESUME_RISKS",
                }
            )
        else:
            patch["__analysis_noncomplete_disposition__"] = "RESUME_FINALIZE"
        return cast(
            WorkAnalysisLocalState,
            {
                **patch,
                "user_interrupt": None,
                "prompt_context": context,
                "policy_confirmation_receipts": list(
                    working.get("policy_confirmation_receipts", [])
                ),
                "__work_analysis_retry_confirmation__": True,
                "trace_context": self._trace(working, "finalize"),
            },
        )

    def _confirmation_patch(
        self,
        state: WorkAnalysisLocalState,
        *,
        origin_target: str,
        question: str,
        reason_code: str,
        options: list[dict[str, str]],
        policy_confirmation: dict[str, object] | None = None,
    ) -> WorkAnalysisLocalState:
        request_intent = cast(Mapping[str, object], state.get("request_intent", {}))
        clarification: request_understanding_contracts.ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": origin_target,
            "question": question,
            "affected_field_paths": [],
            "reason_code": reason_code,
            "known_context_summary": str(request_intent.get("goal", "Work analysis")),
            "options": cast(Any, options),
        }
        interrupt_id = self._id_factory()
        raw_interrupt: dict[str, object] = {
            **build_user_interrupt_v1(clarification),
            "interrupt_id": interrupt_id,
        }
        if policy_confirmation is not None:
            raw_interrupt["policy_confirmation"] = policy_confirmation
        context = dict(cast(Mapping[str, object], state.get("prompt_context", {})))
        context.pop("confirmation_response", None)
        context["confirmation_interrupt"] = {
            "schema_version": 1,
            "interrupt_id": interrupt_id,
            "semantic_owner_id": "WORK_ANALYSIS",
            "origin_target": origin_target,
        }
        return cast(
            WorkAnalysisLocalState,
            {
                "workflow_phase": WorkflowPhase.WAITING_CONFIRMATION.value,
                "user_interrupt": cast(Any, raw_interrupt),
                "prompt_context": context,
            },
        )

    @staticmethod
    def _has_usable_input_route(state: WorkAnalysisLocalState) -> bool:
        plan = state.get("tool_route_plan")
        if not isinstance(plan, Mapping):
            return False
        input_plan = plan.get("input_plan")
        return isinstance(input_plan, Mapping) and bool(input_plan.get("input_routes"))

    @staticmethod
    def _based_on(state: WorkAnalysisLocalState) -> list[StateArtifactRefV1]:
        result: list[StateArtifactRefV1] = []
        route_plan = state.get("tool_route_plan")
        route_artifacts = (
            [route_plan.get("input_plan"), route_plan.get("output_plan")]
            if isinstance(route_plan, Mapping)
            else []
        )
        for artifact in [
            state.get("request_intent"),
            *route_artifacts,
            state.get("retrieval_result"),
        ]:
            meta = artifact.get("meta") if isinstance(artifact, Mapping) else None
            if not isinstance(meta, Mapping):
                continue
            artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
            if isinstance(artifact_id, str) and isinstance(revision, int):
                result.append({"artifact_id": artifact_id, "revision": revision})
        return result

    def _evidence(self, state: WorkAnalysisLocalState) -> list[EvidenceDraftV1]:
        retrieval_result = state.get("retrieval_result")
        if retrieval_result is None:
            return []
        return cast(
            list[EvidenceDraftV1],
            resolve_evidence_projection(
                store=self._evidence_store,
                run_id=state["run_id"],
                retrieval_result=retrieval_result,
            ),
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
        return cast(
            dict[str, object],
            merge_trace_context(
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
            ),
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
                    log_invocation_id = item.get("agent_invocation_id")
                    if isinstance(log_invocation_id, str) and log_invocation_id:
                        return log_invocation_id
        return self._id_factory()

    @staticmethod
    def _has_invocation(state: WorkAnalysisLocalState) -> bool:
        return isinstance(state.get(ANALYSIS_AGENT_LOCAL_KEY), Mapping)


__all__ = ["WorkAnalysisSubgraph"]
