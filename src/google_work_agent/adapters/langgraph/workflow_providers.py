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

from google_work_agent.application.orchestration.assemble_planning_answer import (
    ANSWER_DRAFT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.inspect_plan_output import (
    PLAN_REVIEW_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.orchestration.post_retrieval_envelopes import PlanningResultV2
from google_work_agent.application.orchestration.state_artifacts import WorkAnalysisResultV2
from google_work_agent.application.prompt_runtime.prompt_registry import load_prompt_reference
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.llm import PromptReference
from google_work_agent.ports.system.contracts.observability import ObservabilityContext
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


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
]
