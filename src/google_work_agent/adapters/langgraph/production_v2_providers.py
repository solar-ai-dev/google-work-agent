"""Production semantic-provider adapters for the post-Retrieval V2 cut-over.

These adapters deliberately do not translate legacy semantic artifacts. They
reuse only the currently selected Product Prompt slot and force the approved V2
candidate schema at the LLM boundary. If the active Prompt contract is not
aligned with that schema, StructuredLLMRuntime fails closed; no V1 Prompt or
V1 result fallback is attempted here.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.workflows.planning_answer_v2 import (
    ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.workflows.post_retrieval_envelopes_v2 import PlanningResultV2
from google_work_agent.application.workflows.prompt_registry import load_prompt_reference
from google_work_agent.application.workflows.review_v2 import PLAN_REVIEW_CANDIDATE_OUTPUT_SCHEMA
from google_work_agent.application.workflows.state_artifacts_v2 import WorkAnalysisResultV2, WorkFactV1, WorkRelationV1, WorkAmbiguityV1
from google_work_agent.application.workflows.work_analysis_v2 import (
    WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA,
    WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA,
    WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA,
    WorkAnalysisSemanticInputV1,
)
from google_work_agent.ports import PromptReference, WorkflowStartRequest


class ProductionWorkAnalysisV2CandidateProvider:
    """Three bounded semantic calls over the approved Work Analysis V2 roots."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        request: WorkflowStartRequest,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._request = request
        self._prompt_ref = prompt_ref or load_prompt_reference(
            "work_analysis.analyze", manifest_path
        )

    def extract_work_facts(self, *, semantic_input: WorkAnalysisSemanticInputV1) -> object:
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=semantic_input,
            output_schema=WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA,
            trace_context=self._trace("extract_work_facts"),
        )
        return result.structured_output

    def resolve_relations(
        self,
        *,
        semantic_input: WorkAnalysisSemanticInputV1,
        work_facts: Sequence[WorkFactV1],
    ) -> object:
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={**semantic_input, "work_facts": [dict(item) for item in work_facts]},
            output_schema=WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA,
            trace_context=self._trace("resolve_relations"),
        )
        return result.structured_output

    def assess_analysis_gaps(
        self,
        *,
        semantic_input: WorkAnalysisSemanticInputV1,
        work_facts: Sequence[WorkFactV1],
        validated_relations: Sequence[WorkRelationV1],
        relation_validation_ambiguities: Sequence[WorkAmbiguityV1],
    ) -> object:
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={
                **semantic_input,
                "work_facts": [dict(item) for item in work_facts],
                "validated_relations": [dict(item) for item in validated_relations],
                "relation_validation_ambiguities": [
                    dict(item) for item in relation_validation_ambiguities
                ],
            },
            output_schema=WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA,
            trace_context=self._trace("assess_analysis_gaps"),
        )
        return result.structured_output

    def _trace(self, node: str) -> ObservabilityContext:
        request = self._request
        return ObservabilityContext(
            request_id=request.correlation.request_id,
            command_id=request.correlation.command_id,
            conversation_id=request.conversation_id,
            run_id=request.run_id,
            langgraph_thread_id=request.workflow_key,
            llm_call_id=f"{request.run_id}:work_analysis.{node}.v2",
        )


class ProductionPlanningAnswerV2CandidateProvider:
    """ANSWER semantic producer; AnswerDraftV2 ownership remains deterministic."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref or load_prompt_reference(
            "planning.compose_answer", manifest_path
        )

    def draft_answer(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        work_analysis_result: WorkAnalysisResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
    ) -> object:
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "work_analysis": work_analysis_result,
                "evidence": [dict(item) for item in evidence_drafts],
            },
            output_schema=ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.compose_answer.v2",
            ),
        )
        return result.structured_output


class ProductionReviewV2CandidateProvider:
    """Review semantic producer; official PlanReviewResultV2 is code-owned."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        request: WorkflowStartRequest,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._request = request
        self._prompt_ref = prompt_ref or load_prompt_reference("review.inspect", manifest_path)

    def inspect(
        self,
        *,
        request_intent: RequestIntentV2,
        work_analysis_result: WorkAnalysisResultV2,
        planning_result: PlanningResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
    ) -> object:
        request = self._request
        result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={
                "request_intent": request_intent,
                "work_analysis": work_analysis_result,
                "planning_result": planning_result,
                "evidence": [dict(item) for item in evidence_drafts],
            },
            output_schema=PLAN_REVIEW_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:review.inspect.v2",
            ),
        )
        return result.structured_output


__all__ = [
    "ProductionPlanningAnswerV2CandidateProvider",
    "ProductionReviewV2CandidateProvider",
    "ProductionWorkAnalysisV2CandidateProvider",
]
