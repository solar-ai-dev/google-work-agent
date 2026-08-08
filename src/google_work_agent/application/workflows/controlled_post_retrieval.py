"""Controlled post-retrieval replay helpers for Stage 18 E06-B."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Required, TypedDict, cast

from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.context_retrieval import (
    ContextRetrievalResultV1,
    validate_context_retrieval_result_v1,
)
from google_work_agent.application.workflows.plan_review import (
    PLAN_REVIEW_OUTPUT_SCHEMA,
    PlanReviewResultV1,
    load_plan_review_inspect_prompt_reference,
    validate_plan_review_result_v1,
)
from google_work_agent.application.workflows.profile_fused import (
    ProfilePlanningProjectionV1,
    validate_profile_planning_projection_v1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.workflows.solution_planning import (
    ACTION_PLAN_DRAFT_OUTPUT_SCHEMA,
    ANSWER_DRAFT_OUTPUT_SCHEMA,
    ActionPlanDraftV1,
    AnswerDraftV1,
    load_solution_planning_answer_only_prompt_reference,
    load_solution_planning_draft_plan_prompt_reference,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.workflows.work_analysis import (
    WORK_ANALYSIS_OUTPUT_SCHEMA,
    WorkAnalysisResultV1,
    load_work_analysis_analyze_prompt_reference,
    validate_work_analysis_result_v1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports import OutputSchemaDefinition, PromptReference, StructuredLLMResult

JsonObject = dict[str, object]
ControlledProfileId = Literal[
    "E06B_B1_INTEGRATED",
    "E06B_B2_STAGED",
    "E06B_B3_SPECIALIZED",
]


class ContextReadyReplayInputV1(TypedDict):
    schema_version: Required[Literal[1]]
    contract_version: Literal["CONTEXT_READY_V1"]
    context_snapshot_id: str
    snapshot_origin: str
    source_case_id: str
    fixture_snapshot_id: str
    category: str
    split: str
    request_intent: dict[str, object]
    context_bundle: dict[str, object]
    evidence_set: list[dict[str, object]]
    policy_summary: dict[str, object]


class ContextReadyGoldV1(TypedDict):
    schema_version: Required[Literal[1]]
    contract_version: Literal["CONTEXT_READY_V1"]
    context_snapshot_id: str
    source_case_id: str
    gold: dict[str, object]


class ContextReadyEvaluationItemV1(TypedDict):
    schema_version: Required[Literal[1]]
    evaluation_item_id: str
    contract_version: Literal["CONTEXT_READY_V1"]
    context_snapshot_id: str
    source_case_id: str
    split: str
    model_input_ref: str
    grader_gold_ref: str
    execution_contract: dict[str, object]
    model_input_allowed_ref: str
    grader_only_ref: str


class E06BAnalysisPlanningOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    analysis_result: WorkAnalysisResultV1
    planning_result: ProfilePlanningProjectionV1


class E06BIntegratedOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    analysis_result: WorkAnalysisResultV1
    planning_result: ProfilePlanningProjectionV1
    self_review: PlanReviewResultV1


class ControlledReplayNodeResultV2(TypedDict):
    schema_version: Required[Literal[2]]
    experiment_id: str
    evaluation_item_id: str
    candidate_config_hash: str
    trial_index: int
    target_node_id: str
    upstream_mode: Literal["CONTEXT_READY_REPLAY"]
    result_status: Literal["COMPLETED"]
    graph_profile: str
    agent_subgraph_id: str
    agent_invocation_id: str | None
    agent_invocation_count: int
    prompt_slot_id: str | None
    prompt_version: str | None
    prompt_semantic_bundle_version: str
    output_ref: str | None
    failure_reason_codes: list[str]
    retry_kind: None
    attempt_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    llm_call_count: int
    provider_request_count: int
    communication_token_count: int
    required_field_preservation_rate: float | None
    evidence_id_preservation_rate: float | None
    constraint_loss_count: int
    contradiction_introduced: bool | None
    cost_usd: float
    evaluation_environment_hash: str
    trace_ref: str | None


@dataclass(frozen=True, slots=True)
class ControlledReplayRunResult:
    graph_profile: ControlledProfileId
    candidate_id: str
    evaluation_item_id: str
    context_snapshot_id: str
    fixture_snapshot_id: str
    prompt_semantic_bundle_version: str
    evaluation_environment_hash: str
    agent_invocation_count: int
    llm_call_count: int
    provider_request_count: int
    latency_ms: int
    input_tokens: int
    output_tokens: int
    communication_token_count: int
    trace_context: dict[str, object]
    analysis_result: WorkAnalysisResultV1
    planning_result: ProfilePlanningProjectionV1
    self_review: PlanReviewResultV1 | None
    handoff_metrics: HandoffFidelityMetrics


@dataclass(frozen=True, slots=True)
class HandoffFidelityMetrics:
    required_field_preservation_rate: float | None
    evidence_id_preservation_rate: float | None
    constraint_loss_count: int
    contradiction_introduced: bool | None


class ControlledPostRetrievalReplayError(RuntimeError):
    """Raised when the E06-B replay lane violates its fixed boundary."""


E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="e06b-analysis-planning-output-v2",
    json_schema={
        "type": "object",
        "required": ["schema_version", "analysis_result", "planning_result"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "analysis_result": {"type": "object"},
            "planning_result": {
                "type": "object",
                "required": ["schema_version", "status", "answer_draft", "plan_draft"],
                "additionalProperties": False,
                "properties": {
                    "schema_version": {"type": "integer", "enum": [1]},
                    "status": {
                        "type": "string",
                        "enum": [
                            "ANSWER_ONLY",
                            "PLAN_READY",
                            "NEEDS_CONFIRMATION",
                            "BLOCKED",
                        ],
                    },
                    "answer_draft": {"type": ["object", "null"]},
                    "plan_draft": {"type": ["object", "null"]},
                },
            },
        },
    },
)

E06B_INTEGRATED_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="e06b-integrated-output-v2",
    json_schema={
        "type": "object",
        "required": ["schema_version", "analysis_result", "planning_result", "self_review"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "integer", "enum": [1]},
            "analysis_result": {"type": "object"},
            "planning_result": {
                "type": "object",
                "required": ["schema_version", "status", "answer_draft", "plan_draft"],
                "additionalProperties": False,
                "properties": {
                    "schema_version": {"type": "integer", "enum": [1]},
                    "status": {
                        "type": "string",
                        "enum": [
                            "ANSWER_ONLY",
                            "PLAN_READY",
                            "NEEDS_CONFIRMATION",
                            "BLOCKED",
                        ],
                    },
                    "answer_draft": {"type": ["object", "null"]},
                    "plan_draft": {"type": ["object", "null"]},
                },
            },
            "self_review": {"type": "object"},
        },
    },
)


class ControlledPostRetrievalReplayRunner:
    """Run the E06-B controlled lane without acquisition, retrieval, or Google reads."""

    def __init__(self, *, llm_runtime: Any, manifest_path: Path | None = None) -> None:
        self._llm_runtime = llm_runtime
        self._manifest_path = manifest_path or _registry_default_prompt_manifest_path()

    def run(
        self,
        *,
        experiment_id: str,
        candidate_config: dict[str, object],
        evaluation_item: ContextReadyEvaluationItemV1,
        model_input: ContextReadyReplayInputV1,
        gold: ContextReadyGoldV1,
        trial_index: int = 0,
    ) -> tuple[ControlledReplayRunResult, ControlledReplayNodeResultV2]:
        self._validate_replay_boundary(evaluation_item=evaluation_item, model_input=model_input)
        graph_profile = self._graph_profile(candidate_config)
        context_result = _build_context_result_from_model_input(model_input)
        trace_context: dict[str, object] = {
            "agent_invocation_count": 0,
            "llm_call_count": 0,
            "repair_count": 0,
            "revision_count": 0,
            "agent_node_log": [],
            "prompt_refs": [],
        }
        token_totals = {"input_tokens": 0, "output_tokens": 0, "provider_request_count": 0}
        started = perf_counter()
        if graph_profile == "E06B_B1_INTEGRATED":
            analysis_result, planning_result, review_result, trace_context = self._run_b1(
                model_input=model_input,
                context_result=context_result,
                gold=gold,
                trace_context=trace_context,
                token_totals=token_totals,
            )
        elif graph_profile == "E06B_B2_STAGED":
            analysis_result, planning_result, review_result, trace_context = self._run_b2(
                model_input=model_input,
                context_result=context_result,
                gold=gold,
                trace_context=trace_context,
                token_totals=token_totals,
            )
        else:
            analysis_result, planning_result, review_result, trace_context = self._run_b3(
                model_input=model_input,
                context_result=context_result,
                gold=gold,
                trace_context=trace_context,
                token_totals=token_totals,
            )
        latency_ms = max(0, int((perf_counter() - started) * 1000))
        evaluation_environment_hash = _calculate_evaluation_environment_hash(
            candidate_config=candidate_config,
            evaluation_item=evaluation_item,
        )
        _validate_declared_evaluation_environment_hash(
            candidate_config=candidate_config,
            calculated_hash=evaluation_environment_hash,
        )
        handoff_metrics = _calculate_handoff_fidelity_metrics(
            model_input=model_input,
            gold=gold,
            analysis_result=analysis_result,
            planning_result=planning_result,
        )
        result = ControlledReplayRunResult(
            graph_profile=graph_profile,
            candidate_id=_required_string(candidate_config, "candidate_id"),
            evaluation_item_id=evaluation_item["evaluation_item_id"],
            context_snapshot_id=model_input["context_snapshot_id"],
            fixture_snapshot_id=model_input["fixture_snapshot_id"],
            prompt_semantic_bundle_version=_required_string(
                candidate_config,
                "prompt_semantic_bundle_version",
            ),
            evaluation_environment_hash=evaluation_environment_hash,
            agent_invocation_count=int(trace_context["agent_invocation_count"]),
            llm_call_count=int(trace_context["llm_call_count"]),
            provider_request_count=token_totals["provider_request_count"],
            latency_ms=latency_ms,
            input_tokens=token_totals["input_tokens"],
            output_tokens=token_totals["output_tokens"],
            communication_token_count=0,
            trace_context=trace_context,
            analysis_result=analysis_result,
            planning_result=planning_result,
            self_review=review_result,
            handoff_metrics=handoff_metrics,
        )
        node_result = build_node_run_result_v2(
            experiment_id=experiment_id,
            candidate_config=candidate_config,
            evaluation_item=evaluation_item,
            run_result=result,
            trial_index=trial_index,
        )
        return result, node_result

    def _run_b1(
        self,
        *,
        model_input: ContextReadyReplayInputV1,
        context_result: ContextRetrievalResultV1,
        gold: ContextReadyGoldV1,
        trace_context: dict[str, object],
        token_totals: dict[str, int],
    ) -> tuple[
        WorkAnalysisResultV1,
        ProfilePlanningProjectionV1,
        PlanReviewResultV1,
        dict[str, object],
    ]:
        analysis_prompt_ref = load_e06b_b1_analysis_planning_prompt_reference(self._manifest_path)
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B1_INTEGRATED",
            agent_subgraph_id="e06b_b1",
            agent_role="integrated_post_retrieval_agent",
            agent_invocation_id="e06b-b1-1",
            node_name="init",
            prompt_ref=analysis_prompt_ref,
        )
        analysis_llm = self._invoke(
            prompt_ref=analysis_prompt_ref,
            prompt_input=_build_context_ready_prompt_input(
                model_input=model_input,
                gold=gold,
                mode="ANALYSIS_PLANNING",
            ),
            output_schema=E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA,
            llm_call_id="e06b-b1-1:analysis_planning",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B1_INTEGRATED",
            agent_subgraph_id="e06b_b1",
            agent_role="integrated_post_retrieval_agent",
            agent_invocation_id="e06b-b1-1",
            node_name="analysis_planning",
            llm_call_id="e06b-b1-1:analysis_planning",
            prompt_ref=analysis_prompt_ref,
        )
        _accumulate_tokens(token_totals, analysis_llm)
        fused = validate_e06b_analysis_planning_output_v1(
            analysis_llm.structured_output,
            context_result=context_result,
        )
        review_prompt_ref = load_e06b_b1_self_review_prompt_reference(self._manifest_path)
        review_llm = self._invoke(
            prompt_ref=review_prompt_ref,
            prompt_input=_build_review_prompt_input(
                model_input=model_input,
                gold=gold,
                analysis_result=fused["analysis_result"],
                planning_result=fused["planning_result"],
                review_mode="SELF_REVIEW",
            ),
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            llm_call_id="e06b-b1-1:self_review",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B1_INTEGRATED",
            agent_subgraph_id="e06b_b1",
            agent_role="integrated_post_retrieval_agent",
            agent_invocation_id="e06b-b1-1",
            node_name="self_review",
            llm_call_id="e06b-b1-1:self_review",
            prompt_ref=review_prompt_ref,
        )
        _accumulate_tokens(token_totals, review_llm)
        review = _validate_review_output(
            review_llm.structured_output,
            analysis_result=fused["analysis_result"],
            planning_result=fused["planning_result"],
        )
        return fused["analysis_result"], fused["planning_result"], review, trace_context

    def _run_b2(
        self,
        *,
        model_input: ContextReadyReplayInputV1,
        context_result: ContextRetrievalResultV1,
        gold: ContextReadyGoldV1,
        trace_context: dict[str, object],
        token_totals: dict[str, int],
    ) -> tuple[
        WorkAnalysisResultV1,
        ProfilePlanningProjectionV1,
        PlanReviewResultV1,
        dict[str, object],
    ]:
        analysis_prompt_ref = load_e06b_b2_analysis_planning_prompt_reference(self._manifest_path)
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B2_STAGED",
            agent_subgraph_id="e06b_b2_analysis_planning",
            agent_role="analysis_planning_agent",
            agent_invocation_id="e06b-b2-1",
            node_name="init",
            prompt_ref=analysis_prompt_ref,
        )
        analysis_llm = self._invoke(
            prompt_ref=analysis_prompt_ref,
            prompt_input=_build_context_ready_prompt_input(
                model_input=model_input,
                gold=gold,
                mode="ANALYSIS_PLANNING",
            ),
            output_schema=E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA,
            llm_call_id="e06b-b2-1:analysis_planning",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B2_STAGED",
            agent_subgraph_id="e06b_b2_analysis_planning",
            agent_role="analysis_planning_agent",
            agent_invocation_id="e06b-b2-1",
            node_name="analysis_planning",
            llm_call_id="e06b-b2-1:analysis_planning",
            prompt_ref=analysis_prompt_ref,
        )
        _accumulate_tokens(token_totals, analysis_llm)
        fused = validate_e06b_analysis_planning_output_v1(
            analysis_llm.structured_output,
            context_result=context_result,
        )
        review_prompt_ref = load_plan_review_inspect_prompt_reference(self._manifest_path)
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B2_STAGED",
            agent_subgraph_id="e06b_b2_review",
            agent_role="review_agent",
            agent_invocation_id="e06b-b2-2",
            node_name="init",
            prompt_ref=review_prompt_ref,
        )
        review_llm = self._invoke(
            prompt_ref=review_prompt_ref,
            prompt_input=_build_review_prompt_input(
                model_input=model_input,
                gold=gold,
                analysis_result=fused["analysis_result"],
                planning_result=fused["planning_result"],
                review_mode="STAGED_REVIEW",
            ),
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            llm_call_id="e06b-b2-2:review",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B2_STAGED",
            agent_subgraph_id="e06b_b2_review",
            agent_role="review_agent",
            agent_invocation_id="e06b-b2-2",
            node_name="review",
            llm_call_id="e06b-b2-2:review",
            prompt_ref=review_prompt_ref,
        )
        _accumulate_tokens(token_totals, review_llm)
        review = _validate_review_output(
            review_llm.structured_output,
            analysis_result=fused["analysis_result"],
            planning_result=fused["planning_result"],
        )
        return fused["analysis_result"], fused["planning_result"], review, trace_context

    def _run_b3(
        self,
        *,
        model_input: ContextReadyReplayInputV1,
        context_result: ContextRetrievalResultV1,
        gold: ContextReadyGoldV1,
        trace_context: dict[str, object],
        token_totals: dict[str, int],
    ) -> tuple[
        WorkAnalysisResultV1,
        ProfilePlanningProjectionV1,
        PlanReviewResultV1,
        dict[str, object],
    ]:
        analysis_prompt_ref = load_work_analysis_analyze_prompt_reference(self._manifest_path)
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_analysis",
            agent_role="analysis_agent",
            agent_invocation_id="e06b-b3-1",
            node_name="init",
            prompt_ref=analysis_prompt_ref,
        )
        analysis_llm = self._invoke(
            prompt_ref=analysis_prompt_ref,
            prompt_input=_build_context_ready_prompt_input(
                model_input=model_input,
                gold=gold,
                mode="ANALYSIS_ONLY",
            ),
            output_schema=WORK_ANALYSIS_OUTPUT_SCHEMA,
            llm_call_id="e06b-b3-1:analysis",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_analysis",
            agent_role="analysis_agent",
            agent_invocation_id="e06b-b3-1",
            node_name="analysis",
            llm_call_id="e06b-b3-1:analysis",
            prompt_ref=analysis_prompt_ref,
        )
        _accumulate_tokens(token_totals, analysis_llm)
        analysis_result = validate_work_analysis_result_v1(
            analysis_llm.structured_output,
            context_result=context_result,
        )
        gold_payload = cast(dict[str, object], gold["gold"])
        expected_answer_type = _required_string(gold_payload, "expected_answer_type")
        is_answer_only = expected_answer_type == "ANSWER"
        planning_prompt_ref = (
            load_solution_planning_answer_only_prompt_reference(self._manifest_path)
            if is_answer_only
            else load_solution_planning_draft_plan_prompt_reference(self._manifest_path)
        )
        planning_output_schema = (
            ANSWER_DRAFT_OUTPUT_SCHEMA if is_answer_only else ACTION_PLAN_DRAFT_OUTPUT_SCHEMA
        )
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_planning",
            agent_role="planning_agent",
            agent_invocation_id="e06b-b3-2",
            node_name="init",
            prompt_ref=planning_prompt_ref,
        )
        planning_llm = self._invoke(
            prompt_ref=planning_prompt_ref,
            prompt_input=_build_planning_prompt_input(
                model_input=model_input,
                gold=gold,
                analysis_result=analysis_result,
                answer_only=is_answer_only,
            ),
            output_schema=planning_output_schema,
            llm_call_id="e06b-b3-2:planning",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_planning",
            agent_role="planning_agent",
            agent_invocation_id="e06b-b3-2",
            node_name="planning",
            llm_call_id="e06b-b3-2:planning",
            prompt_ref=planning_prompt_ref,
        )
        _accumulate_tokens(token_totals, planning_llm)
        planning_result = _validate_specialized_planning_output(
            planning_llm.structured_output,
            analysis_result=analysis_result,
            answer_only=is_answer_only,
        )
        review_prompt_ref = load_plan_review_inspect_prompt_reference(self._manifest_path)
        trace_context = _record_agent_start(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_review",
            agent_role="review_agent",
            agent_invocation_id="e06b-b3-3",
            node_name="init",
            prompt_ref=review_prompt_ref,
        )
        review_llm = self._invoke(
            prompt_ref=review_prompt_ref,
            prompt_input=_build_review_prompt_input(
                model_input=model_input,
                gold=gold,
                analysis_result=analysis_result,
                planning_result=planning_result,
                review_mode="SPECIALIZED_REVIEW",
            ),
            output_schema=PLAN_REVIEW_OUTPUT_SCHEMA,
            llm_call_id="e06b-b3-3:review",
        )
        trace_context = _record_llm_call(
            trace_context=trace_context,
            graph_profile="E06B_B3_SPECIALIZED",
            agent_subgraph_id="e06b_b3_review",
            agent_role="review_agent",
            agent_invocation_id="e06b-b3-3",
            node_name="review",
            llm_call_id="e06b-b3-3:review",
            prompt_ref=review_prompt_ref,
        )
        _accumulate_tokens(token_totals, review_llm)
        review = _validate_review_output(
            review_llm.structured_output,
            analysis_result=analysis_result,
            planning_result=planning_result,
        )
        return analysis_result, planning_result, review, trace_context

    def _invoke(
        self,
        *,
        prompt_ref: PromptReference,
        prompt_input: dict[str, object],
        output_schema: OutputSchemaDefinition,
        llm_call_id: str,
    ) -> StructuredLLMResult:
        return self._llm_runtime.invoke_structured(
            prompt_ref=prompt_ref,
            prompt_input=prompt_input,
            output_schema=output_schema,
            trace_context=ObservabilityContext(
                request_id=llm_call_id,
                command_id=llm_call_id,
                conversation_id="controlled-post-retrieval",
                run_id=llm_call_id,
                langgraph_thread_id="e06b-controlled-replay",
                llm_call_id=llm_call_id,
            ),
        )

    def _validate_replay_boundary(
        self,
        *,
        evaluation_item: ContextReadyEvaluationItemV1,
        model_input: ContextReadyReplayInputV1,
    ) -> None:
        if evaluation_item["contract_version"] != "CONTEXT_READY_V1":
            raise ControlledPostRetrievalReplayError("evaluation item must be CONTEXT_READY_V1")
        if model_input["contract_version"] != "CONTEXT_READY_V1":
            raise ControlledPostRetrievalReplayError("model input must be CONTEXT_READY_V1")
        if evaluation_item["context_snapshot_id"] != model_input["context_snapshot_id"]:
            raise ControlledPostRetrievalReplayError("context_snapshot_id must stay fixed")
        execution_contract = evaluation_item["execution_contract"]
        if execution_contract.get("google_read_call_count") != 0:
            raise ControlledPostRetrievalReplayError("E06-B requires Google Read count 0")
        if execution_contract.get("acquisition_executed") is not False:
            raise ControlledPostRetrievalReplayError("E06-B forbids acquisition execution")
        if execution_contract.get("retrieval_executed") is not False:
            raise ControlledPostRetrievalReplayError("E06-B forbids retrieval execution")

    def _graph_profile(self, candidate_config: dict[str, object]) -> ControlledProfileId:
        graph_version = _required_string(candidate_config, "graph_version")
        allowed = {"E06B_B1_INTEGRATED", "E06B_B2_STAGED", "E06B_B3_SPECIALIZED"}
        if graph_version not in allowed:
            raise ControlledPostRetrievalReplayError(
                f"unsupported controlled graph profile: {graph_version}"
            )
        return cast(ControlledProfileId, graph_version)


def validate_e06b_analysis_planning_output_v1(
    value: object,
    *,
    context_result: ContextRetrievalResultV1,
) -> E06BAnalysisPlanningOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(root, "$", {"schema_version", "analysis_result", "planning_result"})
    _require_schema_version(root, "$")
    analysis_result = validate_work_analysis_result_v1(
        root["analysis_result"],
        context_result=context_result,
    )
    planning_result = validate_profile_planning_projection_v1(
        root["planning_result"],
        analysis_result=analysis_result,
    )
    return {
        "schema_version": 1,
        "analysis_result": analysis_result,
        "planning_result": planning_result,
    }


def validate_e06b_integrated_output_v1(
    value: object,
    *,
    context_result: ContextRetrievalResultV1,
) -> E06BIntegratedOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {"schema_version", "analysis_result", "planning_result", "self_review"},
    )
    _require_schema_version(root, "$")
    fused = validate_e06b_analysis_planning_output_v1(
        {
            "schema_version": root["schema_version"],
            "analysis_result": root["analysis_result"],
            "planning_result": root["planning_result"],
        },
        context_result=context_result,
    )
    review = _validate_review_output(
        root["self_review"],
        analysis_result=fused["analysis_result"],
        planning_result=fused["planning_result"],
    )
    return {
        "schema_version": 1,
        "analysis_result": fused["analysis_result"],
        "planning_result": fused["planning_result"],
        "self_review": review,
    }


def load_e06b_b1_analysis_planning_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "e06b.b1.analysis_planning.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_e06b_b1_self_review_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "e06b.b1.self_review.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_e06b_b2_analysis_planning_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "e06b.b2.analysis_planning.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def build_node_run_result_v2(
    *,
    experiment_id: str,
    candidate_config: dict[str, object],
    evaluation_item: ContextReadyEvaluationItemV1,
    run_result: ControlledReplayRunResult,
    trial_index: int,
) -> ControlledReplayNodeResultV2:
    prompt_refs = cast(list[dict[str, object]], run_result.trace_context["prompt_refs"])
    first_prompt = prompt_refs[0] if prompt_refs else None
    return {
        "schema_version": 2,
        "experiment_id": experiment_id,
        "evaluation_item_id": evaluation_item["evaluation_item_id"],
        "candidate_config_hash": _required_string(candidate_config, "candidate_config_hash"),
        "trial_index": trial_index,
        "target_node_id": run_result.graph_profile.lower(),
        "upstream_mode": "CONTEXT_READY_REPLAY",
        "result_status": "COMPLETED",
        "graph_profile": run_result.graph_profile,
        "agent_subgraph_id": _agent_subgraph_id_for_profile(run_result.graph_profile),
        "agent_invocation_id": None,
        "agent_invocation_count": run_result.agent_invocation_count,
        "prompt_slot_id": None if first_prompt is None else cast(str, first_prompt["prompt_id"]),
        "prompt_version": None
        if first_prompt is None
        else cast(str, first_prompt["prompt_version"]),
        "prompt_semantic_bundle_version": run_result.prompt_semantic_bundle_version,
        "output_ref": None,
        "failure_reason_codes": [],
        "retry_kind": None,
        "attempt_count": 1,
        "latency_ms": run_result.latency_ms,
        "input_tokens": run_result.input_tokens,
        "output_tokens": run_result.output_tokens,
        "llm_call_count": run_result.llm_call_count,
        "provider_request_count": run_result.provider_request_count,
        "communication_token_count": run_result.communication_token_count,
        "required_field_preservation_rate": (
            run_result.handoff_metrics.required_field_preservation_rate
        ),
        "evidence_id_preservation_rate": run_result.handoff_metrics.evidence_id_preservation_rate,
        "constraint_loss_count": run_result.handoff_metrics.constraint_loss_count,
        "contradiction_introduced": run_result.handoff_metrics.contradiction_introduced,
        "cost_usd": 0.0,
        "evaluation_environment_hash": run_result.evaluation_environment_hash,
        "trace_ref": None,
    }


def _agent_subgraph_id_for_profile(graph_profile: ControlledProfileId) -> str:
    mapping = {
        "E06B_B1_INTEGRATED": "e06b_b1",
        "E06B_B2_STAGED": "e06b_b2",
        "E06B_B3_SPECIALIZED": "e06b_b3",
    }
    return mapping[graph_profile]


def _build_context_result_from_model_input(
    model_input: ContextReadyReplayInputV1,
) -> ContextRetrievalResultV1:
    evidence_set = model_input["evidence_set"]
    evidence_drafts = [
        {
            "schema_version": 1,
            "evidence_id": _required_string(item, "evidence_id"),
            "resource_handle": f"resource:{_required_string(item, 'resource_id')}",
            "segment_id": _required_string(item, "segment_id"),
            "kind": "excerpt",
            "excerpt": _required_string(item, "excerpt"),
            "locator": {
                "kind": "controlled_post_retrieval_snapshot",
                "resource_id": _required_string(item, "resource_id"),
            },
            "reason_codes": ["CONTROLLED_CONTEXT_READY"],
        }
        for item in evidence_set
    ]
    resource_ids = {_required_string(item, "resource_id") for item in evidence_set}
    selected_segment_ids = [_required_string(item, "segment_id") for item in evidence_set]
    context_result = {
        "schema_version": 1,
        "status": "SUFFICIENT",
        "context_bundle": {
            "schema_version": 1,
            "resource_refs": [
                {
                    "resource_handle": f"resource:{resource_id}",
                    "resource_type": "snapshot_resource",
                    "resource_id": resource_id,
                }
                for resource_id in sorted(resource_ids)
            ],
            "segment_refs": [
                {
                    "segment_id": draft["segment_id"],
                    "resource_handle": draft["resource_handle"],
                }
                for draft in evidence_drafts
            ],
            "evidence_refs": [draft["evidence_id"] for draft in evidence_drafts],
            "normalized_context": [
                {
                    "resource_handle": draft["resource_handle"],
                    "segment_id": draft["segment_id"],
                    "excerpt": draft["excerpt"],
                    "claim": cast(str, evidence_set[index]["claim"]),
                }
                for index, draft in enumerate(evidence_drafts)
            ],
            "missing_information": [],
            "ambiguity": None,
        },
        "evidence_drafts": evidence_drafts,
        "selected_segment_ids": selected_segment_ids,
        "excluded_resource_handles": [],
        "missing_slots": [],
        "additional_acquisition_request": None,
        "sufficiency": {"summary": "controlled context ready replay"},
        "llm_provider_result": {
            "provider": "controlled-replay",
            "model": "N/A",
            "requested_mode": "API_LLM",
            "actual_runtime": "API_LLM",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_ms": 0,
            "fallback_reason": None,
            "structured_output_attempts": 0,
            "provider_request_id": None,
            "safe_error_code": None,
        },
    }
    return validate_context_retrieval_result_v1(context_result)


def _calculate_evaluation_environment_hash(
    *,
    candidate_config: dict[str, object],
    evaluation_item: ContextReadyEvaluationItemV1,
) -> str:
    runtime = _require_mapping(candidate_config.get("runtime"), "runtime")
    parameters = cast(dict[str, object], runtime.get("parameters", {}))
    evaluation_environment = _require_mapping(
        candidate_config.get("evaluation_environment"),
        "evaluation_environment",
    )
    graph_profile_spec = _require_mapping(
        candidate_config.get("graph_profile_spec"),
        "graph_profile_spec",
    )
    payload = {
        "dataset_version": _required_string(candidate_config, "dataset_version"),
        "tool_schema_version": _required_string(candidate_config, "tool_schema_version"),
        "policy_version": _required_string(candidate_config, "policy_version"),
        "prompt_semantic_bundle_version": _required_string(
            candidate_config,
            "prompt_semantic_bundle_version",
        ),
        "graph_profile": _required_string(graph_profile_spec, "profile_id"),
        "runtime": {
            "runtime_mode": _required_string(runtime, "runtime_mode"),
            "provider": _required_string(runtime, "provider"),
            "model": _required_string(runtime, "model"),
            "model_version": _required_string(runtime, "model_version"),
            "parameters": parameters,
        },
        "evaluation_environment": {
            "environment_lock_version": _required_string(
                evaluation_environment,
                "environment_lock_version",
            ),
            "client_os": _required_string(evaluation_environment, "client_os"),
            "llm_concurrency": _required_int(evaluation_environment, "llm_concurrency"),
            "google_read_concurrency": _required_int(
                evaluation_environment,
                "google_read_concurrency",
            ),
            "write_concurrency": _required_int(evaluation_environment, "write_concurrency"),
            "api_llm_timeout_seconds": _required_int(
                evaluation_environment,
                "api_llm_timeout_seconds",
            ),
            "google_timeout_seconds": _required_int(
                evaluation_environment,
                "google_timeout_seconds",
            ),
            "runner_version": _required_string(evaluation_environment, "runner_version"),
            "hardware_profile_id": _required_string(
                evaluation_environment,
                "hardware_profile_id",
            ),
        },
        "execution_contract": evaluation_item["execution_contract"],
        "context_ready_contract_version": evaluation_item["contract_version"],
    }
    return calculate_canonical_json_hash(payload)


def _validate_declared_evaluation_environment_hash(
    *,
    candidate_config: dict[str, object],
    calculated_hash: str,
) -> None:
    declared_hash = _required_string(
        _require_mapping(candidate_config.get("evaluation_environment"), "evaluation_environment"),
        "evaluation_environment_hash",
    )
    if declared_hash != calculated_hash:
        raise ControlledPostRetrievalReplayError(
            "evaluation_environment_hash mismatch for candidate config"
        )


def _calculate_handoff_fidelity_metrics(
    *,
    model_input: ContextReadyReplayInputV1,
    gold: ContextReadyGoldV1,
    analysis_result: WorkAnalysisResultV1,
    planning_result: ProfilePlanningProjectionV1,
) -> HandoffFidelityMetrics:
    required_evidence_ids = sorted(
        {
            *[_normalize_string(item) for item in analysis_result["evidence_refs"]],
            *[
                _normalize_string(item)
                for item in cast(
                    list[object],
                    model_input["context_bundle"].get("evidence_ids", []),
                )
            ],
        }
    )
    required_resource_refs = sorted(
        {
            *[
                _normalize_string(_required_string(item, "resource_handle"))
                for item in analysis_result["resource_refs"]
            ]
        }
    )
    downstream_evidence_ids = _collect_planning_evidence_ids(planning_result)
    downstream_resource_refs = _collect_planning_resource_refs(planning_result)
    preserved_required_fields = 0
    total_required_fields = len(required_evidence_ids) + len(required_resource_refs)
    preserved_required_fields += sum(
        1 for item in required_evidence_ids if item in downstream_evidence_ids
    )
    preserved_required_fields += sum(
        1 for item in required_resource_refs if item in downstream_resource_refs
    )
    required_field_preservation_rate = (
        None if total_required_fields == 0 else preserved_required_fields / total_required_fields
    )
    evidence_id_preservation_rate = (
        None
        if not required_evidence_ids
        else sum(1 for item in required_evidence_ids if item in downstream_evidence_ids)
        / len(required_evidence_ids)
    )
    forbidden_tools = {
        _normalize_string(item)
        for item in cast(
            list[object],
            cast(dict[str, object], gold["gold"]).get("forbidden_actions", []),
        )
    }
    action_tools = _collect_planning_action_tools(planning_result)
    forbidden_action_uses = action_tools & forbidden_tools
    unexpected_evidence_ids = downstream_evidence_ids - set(required_evidence_ids)
    unexpected_resource_refs = downstream_resource_refs - set(required_resource_refs)
    constraint_loss_count = (
        sum(1 for item in required_resource_refs if item not in downstream_resource_refs)
        + sum(1 for item in required_evidence_ids if item not in downstream_evidence_ids)
        + len(forbidden_action_uses)
    )
    contradiction_introduced = bool(
        forbidden_action_uses or unexpected_evidence_ids or unexpected_resource_refs
    )
    return HandoffFidelityMetrics(
        required_field_preservation_rate=required_field_preservation_rate,
        evidence_id_preservation_rate=evidence_id_preservation_rate,
        constraint_loss_count=constraint_loss_count,
        contradiction_introduced=contradiction_introduced,
    )


def _collect_planning_evidence_ids(planning_result: ProfilePlanningProjectionV1) -> set[str]:
    evidence_ids: set[str] = set()
    answer_draft = planning_result["answer_draft"]
    if answer_draft is not None:
        evidence_ids.update(_normalize_string(item) for item in answer_draft["evidence_refs"])
    plan_draft = planning_result["plan_draft"]
    if plan_draft is not None:
        evidence_ids.update(_normalize_string(item) for item in plan_draft["evidence_refs"])
    return evidence_ids


def _collect_planning_resource_refs(planning_result: ProfilePlanningProjectionV1) -> set[str]:
    resource_refs: set[str] = set()
    answer_draft = planning_result["answer_draft"]
    if answer_draft is not None:
        resource_refs.update(
            _normalize_string(_required_string(item, "resource_handle"))
            for item in answer_draft["resource_refs"]
        )
    plan_draft = planning_result["plan_draft"]
    if plan_draft is not None:
        resource_refs.update(
            _normalize_string(_required_string(item, "resource_handle"))
            for item in plan_draft["resource_refs"]
        )
    return resource_refs


def _collect_planning_action_tools(planning_result: ProfilePlanningProjectionV1) -> set[str]:
    plan_draft = planning_result["plan_draft"]
    if plan_draft is None:
        return set()
    return {_normalize_string(action["tool_name"]) for action in plan_draft["actions"]}


def _normalize_string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("expected string value")
    normalized = value.strip()
    if not normalized:
        raise ValueError("string value must not be blank")
    return normalized


def _build_context_ready_prompt_input(
    *,
    model_input: ContextReadyReplayInputV1,
    gold: ContextReadyGoldV1,
    mode: str,
) -> dict[str, object]:
    return {
        "mode": mode,
        "contract_version": model_input["contract_version"],
        "context_snapshot_id": model_input["context_snapshot_id"],
        "fixture_snapshot_id": model_input["fixture_snapshot_id"],
        "request_intent": model_input["request_intent"],
        "context_bundle": model_input["context_bundle"],
        "evidence_set": model_input["evidence_set"],
        "policy_summary": model_input["policy_summary"],
        "expected_answer_type": cast(dict[str, object], gold["gold"]).get("expected_answer_type"),
        "source_content_is_untrusted": True,
    }


def _build_planning_prompt_input(
    *,
    model_input: ContextReadyReplayInputV1,
    gold: ContextReadyGoldV1,
    analysis_result: WorkAnalysisResultV1,
    answer_only: bool,
) -> dict[str, object]:
    payload = _build_context_ready_prompt_input(
        model_input=model_input,
        gold=gold,
        mode="ANSWER_ONLY" if answer_only else "PLAN_READY",
    )
    payload["analysis_result"] = analysis_result
    return payload


def _build_review_prompt_input(
    *,
    model_input: ContextReadyReplayInputV1,
    gold: ContextReadyGoldV1,
    analysis_result: WorkAnalysisResultV1,
    planning_result: ProfilePlanningProjectionV1,
    review_mode: str,
) -> dict[str, object]:
    payload = _build_context_ready_prompt_input(
        model_input=model_input,
        gold=gold,
        mode=review_mode,
    )
    payload["analysis_result"] = analysis_result
    payload["planning_result"] = planning_result
    return payload


def _validate_specialized_planning_output(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
    answer_only: bool,
) -> ProfilePlanningProjectionV1:
    if answer_only:
        answer_draft = validate_answer_draft_v1(value, analysis_result=analysis_result)
        return {
            "schema_version": 1,
            "status": answer_draft["status"],
            "answer_draft": answer_draft,
            "plan_draft": None,
        }
    plan_draft = validate_action_plan_draft_v1(value, analysis_result=analysis_result)
    return {
        "schema_version": 1,
        "status": plan_draft["status"],
        "answer_draft": None,
        "plan_draft": plan_draft,
    }


def _validate_review_output(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
    planning_result: ProfilePlanningProjectionV1,
) -> PlanReviewResultV1:
    return validate_plan_review_result_v1(
        value,
        target_kind="ANSWER" if planning_result["answer_draft"] is not None else "PLAN",
        analysis_result=analysis_result,
        answer_draft=cast(AnswerDraftV1 | None, planning_result["answer_draft"]),
        plan_draft=cast(ActionPlanDraftV1 | None, planning_result["plan_draft"]),
    )


def _record_agent_start(
    *,
    trace_context: dict[str, object],
    graph_profile: str,
    agent_subgraph_id: str,
    agent_role: str,
    agent_invocation_id: str,
    node_name: str,
    prompt_ref: PromptReference,
) -> dict[str, object]:
    return merge_trace_context(
        {"trace_context": trace_context},
        graph_profile=graph_profile,
        agent_subgraph_id=agent_subgraph_id,
        agent_role=agent_role,
        agent_invocation_id=agent_invocation_id,
        subgraph_namespace=agent_subgraph_id,
        node_name=node_name,
        prompt_ref=prompt_ref,
        agent_invocation_increment=1,
    )


def _record_llm_call(
    *,
    trace_context: dict[str, object],
    graph_profile: str,
    agent_subgraph_id: str,
    agent_role: str,
    agent_invocation_id: str,
    node_name: str,
    llm_call_id: str,
    prompt_ref: PromptReference,
) -> dict[str, object]:
    return merge_trace_context(
        {"trace_context": trace_context},
        graph_profile=graph_profile,
        agent_subgraph_id=agent_subgraph_id,
        agent_role=agent_role,
        agent_invocation_id=agent_invocation_id,
        subgraph_namespace=agent_subgraph_id,
        node_name=node_name,
        llm_call_id=llm_call_id,
        prompt_ref=prompt_ref,
        llm_call_increment=1,
    )


def _accumulate_tokens(
    totals: dict[str, int],
    result: StructuredLLMResult,
) -> None:
    totals["input_tokens"] += result.input_tokens or 0
    totals["output_tokens"] += result.output_tokens or 0
    totals["provider_request_count"] += result.provider_calls_consumed


def merge_trace_context(
    state: dict[str, object],
    *,
    graph_profile: str,
    agent_subgraph_id: str,
    agent_role: str,
    agent_invocation_id: str,
    subgraph_namespace: str,
    node_name: str,
    llm_call_id: str | None = None,
    prompt_ref: PromptReference | None = None,
    agent_invocation_increment: int = 0,
    llm_call_increment: int = 0,
    repair_increment: int = 0,
    revision_increment: int = 0,
) -> dict[str, object]:
    current = cast(dict[str, object], state.get("trace_context", {}))
    node_log = list(cast(list[dict[str, object]], current.get("agent_node_log", [])))
    prompt_refs = list(cast(list[dict[str, object]], current.get("prompt_refs", [])))
    node_log.append(
        {
            "graph_profile": graph_profile,
            "agent_subgraph_id": agent_subgraph_id,
            "agent_role": agent_role,
            "agent_invocation_id": agent_invocation_id,
            "subgraph_namespace": subgraph_namespace,
            "node_name": node_name,
            "llm_call_id": llm_call_id,
        }
    )
    if prompt_ref is not None:
        prompt_refs.append(_prompt_ref_to_mapping(prompt_ref))
    return {
        **current,
        "agent_invocation_count": int(current.get("agent_invocation_count", 0))
        + agent_invocation_increment,
        "llm_call_count": int(current.get("llm_call_count", 0)) + llm_call_increment,
        "repair_count": int(current.get("repair_count", 0)) + repair_increment,
        "revision_count": int(current.get("revision_count", 0)) + revision_increment,
        "agent_node_log": node_log,
        "prompt_refs": prompt_refs,
    }


def _prompt_ref_to_mapping(prompt_ref: PromptReference) -> dict[str, object]:
    return {
        "prompt_bundle_version": prompt_ref.prompt_bundle_version,
        "prompt_id": prompt_ref.prompt_id,
        "prompt_version": prompt_ref.prompt_version,
        "content_hash": prompt_ref.content_hash,
        "agent_role": prompt_ref.agent_role,
        "subgraph_name": prompt_ref.subgraph_name,
        "node_name": prompt_ref.node_name,
        "node_state": prompt_ref.node_state,
        "purpose": prompt_ref.purpose,
        "input_schema_version": prompt_ref.input_schema_version,
        "output_schema_version": prompt_ref.output_schema_version,
    }


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ControlledPostRetrievalReplayError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ControlledPostRetrievalReplayError(f"{path} keys must be strings")
        result[key] = item
    return result


def _require_exact_keys(value: dict[str, object], path: str, required: set[str]) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing:
        raise ControlledPostRetrievalReplayError(f"{path} missing required keys: {missing}")
    if extra:
        raise ControlledPostRetrievalReplayError(f"{path} contains unsupported keys: {extra}")


def _require_schema_version(value: dict[str, object], path: str) -> None:
    if value.get("schema_version") != 1:
        raise ControlledPostRetrievalReplayError(f"{path}.schema_version must be 1")


def _required_string(item: dict[str, object], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise ControlledPostRetrievalReplayError(f"{field} must be a non-empty string")
    return value


def _required_int(item: dict[str, object], field: str) -> int:
    value = item.get(field)
    if not isinstance(value, int):
        raise ControlledPostRetrievalReplayError(f"{field} must be an integer")
    return value


__all__ = [
    "ControlledPostRetrievalReplayError",
    "ControlledPostRetrievalReplayRunner",
    "ControlledReplayNodeResultV2",
    "ControlledReplayRunResult",
    "ContextReadyEvaluationItemV1",
    "ContextReadyGoldV1",
    "ContextReadyReplayInputV1",
    "E06B_ANALYSIS_PLANNING_OUTPUT_SCHEMA",
    "E06B_INTEGRATED_OUTPUT_SCHEMA",
    "E06BAnalysisPlanningOutputV1",
    "E06BIntegratedOutputV1",
    "build_node_run_result_v2",
    "load_e06b_b1_analysis_planning_prompt_reference",
    "load_e06b_b1_self_review_prompt_reference",
    "load_e06b_b2_analysis_planning_prompt_reference",
    "validate_e06b_analysis_planning_output_v1",
    "validate_e06b_integrated_output_v1",
]
