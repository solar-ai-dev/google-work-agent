"""Runtime V2 ACTION argument preparation and composition boundary.

This module deliberately leaves the legacy PlanningArgumentOrchestrator.compose/
revise authority untouched until the atomic Main Graph cut-over.  Runtime V2
reuses only its deterministic ``prepare_actions`` boundary, then invokes a V2
argument writer with ``WorkAnalysisResultV2``.  No V1->V2 semantic conversion
exists here.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
)
from google_work_agent.application.orchestration.planning_argument_orchestrator import (
    PlanningActionPreparationResultV1,
    PlanningArgumentOrchestrator,
    RouteArgumentResult,
    validate_planning_action_preparation_result_v1,
)
from google_work_agent.application.orchestration.planning_argument_writer import (
    TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.orchestration.planning_arguments import (
    BoundSelectedToolSchemaV1,
    ToolArgumentCandidateV1,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.orchestration.prompt_registry import (
    default_prompt_manifest_path as _default_prompt_manifest_path,
)
from google_work_agent.application.orchestration.prompt_registry import (
    load_prompt_reference as _load_prompt_reference,
)
from google_work_agent.application.orchestration.state_artifacts import WorkAnalysisResultV2
from google_work_agent.application.orchestration.tool_routing import OutputToolRouteV1
from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    StructuredLLMRuntime,
)
from google_work_agent.ports.events.observability_events import ObservabilityContext
from google_work_agent.ports.llm import (
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest


class PlanningArgumentWriterV2Protocol(Protocol):
    def invoke_v2(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV2,
    ) -> StructuredLLMResult: ...

    def validated_candidate(
        self,
        llm_result: StructuredLLMResult,
        *,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> ToolArgumentCandidateV1: ...


class PlanningArgumentWriterV2:
    """Write business arguments for one already-bound frozen output route."""

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        manifest = manifest_path or _default_prompt_manifest_path()
        self._llm_runtime = llm_runtime
        self._prompt_ref = prompt_ref or _load_prompt_reference(
            "planning.compose_arguments",
            manifest,
        )

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    def invoke_v2(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV2,
    ) -> StructuredLLMResult:
        allowed_evidence_refs = {draft["evidence_id"] for draft in evidence_drafts}
        return self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input={
                "user_request": request.request_text,
                "request_intent": request_intent,
                "output_route": {
                    "route_id": bound_tool_schema["route_id"],
                    "connector_id": bound_tool_schema["connector_id"],
                    "resource_type": bound_tool_schema["resource_type"],
                    "effect": bound_tool_schema["effect"],
                    "selected_tool_id": bound_tool_schema["selected_tool_id"],
                },
                "selected_tool_schema": bound_tool_schema["argument_schema"],
                "work_analysis": analysis_result,
                "evidence": _planning_evidence_projection(evidence_drafts),
            },
            output_schema=TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.compose_arguments:{bound_tool_schema['route_id']}",
            ),
            semantic_validate=lambda candidate: validate_tool_argument_candidate_v1(
                candidate,
                bound_tool_schema=bound_tool_schema,
                allowed_evidence_refs=allowed_evidence_refs,
            ),
        )

    @staticmethod
    def validated_candidate(
        llm_result: StructuredLLMResult,
        *,
        bound_tool_schema: BoundSelectedToolSchemaV1,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> ToolArgumentCandidateV1:
        return validate_tool_argument_candidate_v1(
            llm_result.structured_output,
            bound_tool_schema=bound_tool_schema,
            allowed_evidence_refs={draft["evidence_id"] for draft in evidence_drafts},
        )


class PlanningArgumentOrchestratorV2:
    """V2 ACTION authority: prepare_actions -> compose_prepared only."""

    def __init__(
        self,
        *,
        preparer: PlanningArgumentOrchestrator,
        writer: PlanningArgumentWriterV2Protocol,
    ) -> None:
        self._preparer = preparer
        self._writer = writer

    def prepare_actions(
        self,
        *,
        output_routes: tuple[OutputToolRouteV1, ...],
    ) -> tuple[PlanningActionPreparationResultV1, ...]:
        return self._preparer.prepare_actions(output_routes=output_routes)

    def compose_prepared(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        preparations: tuple[PlanningActionPreparationResultV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV2,
    ) -> tuple[RouteArgumentResult, ...]:
        if not output_routes:
            raise ValueError("ACTION planning requires at least one frozen output route")
        if len(preparations) != len(output_routes):
            raise ValueError("PlanningActionPreparationResultV1 count must match output routes")
        results: list[RouteArgumentResult] = []
        for route, raw_preparation in zip(output_routes, preparations, strict=True):
            preparation = validate_planning_action_preparation_result_v1(raw_preparation)
            if preparation["route_id"] != route["route_id"]:
                raise ValueError("PlanningActionPreparationResultV1 route_id escapes frozen route")
            if preparation["disposition"] != "READY":
                raise ValueError("Argument Writer may only be invoked for READY preparation")
            bound_schema = preparation["bound_tool_schema"]
            _assert_bound_schema_matches_route(bound_schema, route=route)
            llm_result = self._writer.invoke_v2(
                request=request,
                request_intent=request_intent,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
            )
            candidate = self._writer.validated_candidate(
                llm_result,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
            )
            results.append(RouteArgumentResult(route, bound_schema, candidate, llm_result))
        return tuple(results)


def _assert_bound_schema_matches_route(
    bound_schema: Mapping[str, object],
    *,
    route: OutputToolRouteV1,
) -> None:
    expected = {
        "route_id": route["route_id"],
        "connector_id": route["connector_id"],
        "resource_type": route["resource_type"],
        "effect": route["effect"],
        "selected_tool_id": route["selected_tool_id"],
    }
    for key, value in expected.items():
        if bound_schema.get(key) != value:
            raise ValueError(f"bound selected Tool schema escapes frozen route: {key}")


def _planning_evidence_projection(
    evidence_drafts: Sequence[EvidenceDraftV1],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for draft in evidence_drafts:
        role = next(
            (
                code
                for code in draft["reason_codes"]
                if code in {"SUPPORTS", "CONTRADICTS", "CONTEXT"}
            ),
            "CONTEXT",
        )
        result.append(
            {
                "evidence_ref": draft["evidence_id"],
                "excerpt": draft["excerpt"],
                "role": role,
                "resource_ref": draft["resource_handle"],
            }
        )
    return result


__all__ = [
    "PlanningArgumentOrchestratorV2",
    "PlanningArgumentWriterV2",
    "PlanningArgumentWriterV2Protocol",
]
