"""V2-only Planning revision owner for Review REVISE.

Checkpoint B's initial PlanningV2Producer is intentionally unchanged. This
module handles the distinct corrective path without converting a legacy plan
into V2 authority: the current ActionPlanDraftV2 is the sole revision base,
Review V2 issues define the bounded failure record, frozen Tool Route identity
is re-bound deterministically, and only business arguments/evidence may change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
    RetrievalResultV1,
    SubgraphReturnV2,
)
from google_work_agent.application.workflows.planning_argument_orchestrator import (
    PlanningActionPreparationResultV1,
)
from google_work_agent.application.workflows.planning_argument_orchestrator_v2 import (
    PlanningArgumentOrchestratorV2,
)
from google_work_agent.application.workflows.planning_argument_writer import (
    TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
)
from google_work_agent.application.workflows.planning_arguments import (
    ToolArgumentCandidateV1,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.workflows.planning_plan_assembler import (
    ActionPlanDraftV2,
    assemble_action_plan_draft_v2,
    materialize_action_seeds,
)
from google_work_agent.application.workflows.post_retrieval_envelopes_v2 import (
    PlanningResultV2,
    validate_planning_return_v2,
)
from google_work_agent.application.workflows.prompt_registry import load_prompt_reference
from google_work_agent.application.workflows.state_artifacts_v2 import (
    PlanReviewResultV2,
    WorkAnalysisResultV2,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2, output_routes
from google_work_agent.ports import PromptReference, WorkflowStartRequest


class PlanningV2RevisionError(ValueError):
    pass


class PlanningV2RevisionProducer:
    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        argument_orchestrator: PlanningArgumentOrchestratorV2,
        prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._argument_orchestrator = argument_orchestrator
        self._prompt_ref = prompt_ref or load_prompt_reference(
            "planning.compose_arguments.revise", manifest_path
        )

    def run(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        tool_route_plan: ToolRoutePlanV2,
        retrieval_result: RetrievalResultV1,
        work_analysis_result: WorkAnalysisResultV2,
        current_plan: ActionPlanDraftV2,
        review_result: PlanReviewResultV2,
        evidence_drafts: Sequence[EvidenceDraftV1],
    ) -> SubgraphReturnV2[PlanningResultV2]:
        if review_result["status"] != "REVISE":
            raise PlanningV2RevisionError("Planning revision requires Review V2 REVISE")
        required_review_ref = {
            "artifact_id": current_plan["meta"]["artifact_id"],
            "revision": current_plan["meta"]["revision"],
        }
        if required_review_ref not in review_result["meta"]["based_on"]:
            raise PlanningV2RevisionError("stale Review V2 for current Planning V2 revision")

        routes = output_routes(tool_route_plan)
        if not routes:
            raise PlanningV2RevisionError("ACTION revision requires frozen output routes")
        preparations = self._argument_orchestrator.prepare_actions(output_routes=routes)
        ready_by_route = self._ready_preparations(preparations)
        action_by_route = {action["route_id"]: action for action in current_plan["actions"]}
        if set(action_by_route) != {route["route_id"] for route in routes}:
            raise PlanningV2RevisionError("current plan no longer matches frozen output routes")

        evidence = list(evidence_drafts)
        allowed_evidence_refs = {item["evidence_id"] for item in evidence}
        revised_candidates: list[ToolArgumentCandidateV1] = []
        for route in routes:
            route_id = route["route_id"]
            action = action_by_route[route_id]
            if action["tool_id"] != route["selected_tool_id"] or action["effect"] != route["effect"]:
                raise PlanningV2RevisionError("current action escapes frozen Tool Route authority")
            bound = ready_by_route[route_id]["bound_tool_schema"]
            current_candidate = validate_tool_argument_candidate_v1(
                {
                    "schema_version": 1,
                    "route_id": route_id,
                    "arguments": dict(action["arguments"]),
                    "evidence_refs": list(action["evidence_refs"]),
                },
                bound_tool_schema=bound,
                allowed_evidence_refs=allowed_evidence_refs,
            )
            issues = [
                issue
                for issue in review_result["issues"]
                if issue["action_id"] is None or issue["action_id"] == action["action_id"]
            ]
            if not issues:
                revised_candidates.append(current_candidate)
                continue
            llm_result = self._llm_runtime.invoke_structured(
                prompt_ref=self._prompt_ref,
                prompt_input={
                    "base_projection": {
                        "user_request": request.request_text,
                        "request_intent": request_intent,
                        "output_route": {
                            "route_id": route_id,
                            "connector_id": route["connector_id"],
                            "resource_type": route["resource_type"],
                            "effect": route["effect"],
                            "selected_tool_id": route["selected_tool_id"],
                        },
                        "selected_tool_schema": bound["argument_schema"],
                        "work_analysis": work_analysis_result,
                        "evidence": _evidence_projection(evidence),
                    },
                    "candidate_output": current_candidate,
                    "failure_record": {
                        "failure_reason_codes": _ordered_unique(
                            issue["code"] for issue in issues
                        ),
                        "affected_fields": ["$.arguments", "$.evidence_refs"],
                        "allowed_change_scope": ["$.arguments", "$.evidence_refs"],
                        "summary": "; ".join(issue["description"] for issue in issues),
                    },
                },
                output_schema=TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA,
                trace_context=ObservabilityContext(
                    request_id=request.correlation.request_id,
                    command_id=request.correlation.command_id,
                    conversation_id=request.conversation_id,
                    run_id=request.run_id,
                    langgraph_thread_id=request.workflow_key,
                    llm_call_id=f"{request.run_id}:planning.compose_arguments.revise:{route_id}",
                ),
                semantic_validate=lambda candidate, bound=bound: validate_tool_argument_candidate_v1(
                    candidate,
                    bound_tool_schema=bound,
                    allowed_evidence_refs=allowed_evidence_refs,
                ),
            )
            revised_candidates.append(
                validate_tool_argument_candidate_v1(
                    llm_result.structured_output,
                    bound_tool_schema=bound,
                    allowed_evidence_refs=allowed_evidence_refs,
                )
            )

        seeds = materialize_action_seeds(
            output_routes=routes,
            argument_candidates=revised_candidates,
            action_id_factory=lambda: "unused-action-id",
            action_id_by_route={route_id: action["action_id"] for route_id, action in action_by_route.items()},
        )
        revised_plan = assemble_action_plan_draft_v2(
            artifact_id=current_plan["meta"]["artifact_id"],
            revision=current_plan["meta"]["revision"] + 1,
            based_on=[
                {
                    "artifact_id": current_plan["meta"]["artifact_id"],
                    "revision": current_plan["meta"]["revision"],
                },
                {
                    "artifact_id": tool_route_plan["output_plan"]["meta"]["artifact_id"],
                    "revision": tool_route_plan["output_plan"]["meta"]["revision"],
                },
                {
                    "artifact_id": work_analysis_result["meta"]["artifact_id"],
                    "revision": work_analysis_result["meta"]["revision"],
                },
                {
                    "artifact_id": retrieval_result["meta"]["artifact_id"],
                    "revision": retrieval_result["meta"]["revision"],
                },
            ],
            action_seeds=seeds,
        )
        return cast(
            SubgraphReturnV2[PlanningResultV2],
            validate_planning_return_v2(
                {
                    "disposition": "PLAN_READY",
                    "typed_result": revised_plan,
                    "workflow_signal": None,
                }
            ),
        )

    @staticmethod
    def _ready_preparations(
        preparations: tuple[PlanningActionPreparationResultV1, ...],
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for preparation in preparations:
            if preparation["disposition"] != "READY":
                raise PlanningV2RevisionError(
                    "corrective Planning prerequisites changed; revision must fail closed"
                )
            result[preparation["route_id"]] = cast(Mapping[str, object], preparation)
        return result


def _evidence_projection(
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


def _ordered_unique(values: Sequence[str] | object) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in cast(Sequence[str], values):
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


__all__ = ["PlanningV2RevisionError", "PlanningV2RevisionProducer"]
