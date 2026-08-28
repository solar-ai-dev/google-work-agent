"""Deterministic orchestration of per-output-route Planning argument calls.

Tool Route freezes connector/resource/effect/tool identity. Canonical Workflow
v7.21 / Interface v2.24 add an invocation-local preparation boundary above the
business-argument writer: only READY routes may invoke the writer. A missing
required deterministic container yields NEEDS_CONFIRMATION without an LLM call.
The legacy ``compose`` entry point is intentionally retained unchanged until the
atomic production cut-over.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from google_work_agent.application.orchestration.handoff_contracts import (
    ActionPlanDraftV1,
    ConfirmationRequiredV1,
    EvidenceDraftV1,
    RequestIntentV2,
    ReviewIssueV1,
    WorkAnalysisResultV1,
)
from google_work_agent.application.orchestration.planning_argument_writer import (
    PlanningArgumentWriter,
)
from google_work_agent.application.orchestration.planning_arguments import (
    BoundSelectedToolSchemaV1,
    DefaultContainerResolver,
    PlanningArgumentBindingError,
    RequiredContainerUnresolvedError,
    ToolArgumentCandidateV1,
    validate_tool_argument_candidate_v1,
)
from google_work_agent.application.orchestration.planning_tool_schemas import (
    planning_tool_argument_schema,
)
from google_work_agent.application.orchestration.tool_routing import OutputToolRouteV1
from google_work_agent.ports.llm import (
    PromptReference,
    StructuredLLMResult,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


class PlanningActionPreparationReadyV1(TypedDict):
    disposition: Literal["READY"]
    route_id: str
    bound_tool_schema: BoundSelectedToolSchemaV1


class PlanningActionPreparationNeedsConfirmationV1(TypedDict):
    disposition: Literal["NEEDS_CONFIRMATION"]
    route_id: str
    question: str
    options: list[str]
    reason_codes: list[str]


class PlanningActionPreparationRouteReconsiderationV1(TypedDict):
    disposition: Literal["ROUTE_RECONSIDERATION_REQUIRED"]
    route_id: str
    reason_codes: list[str]


class PlanningActionPreparationBlockedV1(TypedDict):
    disposition: Literal["BLOCKED"]
    route_id: str
    reason_codes: list[str]


PlanningActionPreparationResultV1 = (
    PlanningActionPreparationReadyV1
    | PlanningActionPreparationNeedsConfirmationV1
    | PlanningActionPreparationRouteReconsiderationV1
    | PlanningActionPreparationBlockedV1
)


@dataclass(frozen=True, slots=True)
class RouteArgumentResult:
    route: OutputToolRouteV1
    bound_tool_schema: BoundSelectedToolSchemaV1
    candidate: ToolArgumentCandidateV1
    llm_result: StructuredLLMResult | None


class PlanningArgumentOrchestrator:
    """Run the canonical Argument Writer independently for each output route."""

    def __init__(
        self,
        *,
        writer: PlanningArgumentWriter,
        default_container_resolver: DefaultContainerResolver,
        explicit_container_provider: Callable[[OutputToolRouteV1], str | None] | None = None,
    ) -> None:
        self._writer = writer
        self._default_container_resolver = default_container_resolver
        self._explicit_container_provider = explicit_container_provider

    @property
    def prompt_ref(self) -> PromptReference:
        return self._writer.prompt_ref

    @property
    def revise_prompt_ref(self) -> PromptReference:
        return self._writer.revise_prompt_ref

    def prepare_actions(
        self,
        *,
        output_routes: tuple[OutputToolRouteV1, ...],
    ) -> tuple[PlanningActionPreparationResultV1, ...]:
        """Resolve deterministic prerequisites without invoking the Argument Writer."""
        self._validate_output_routes(output_routes)
        return tuple(self._prepare_route(route) for route in output_routes)

    def compose_prepared(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        preparations: tuple[PlanningActionPreparationResultV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
    ) -> tuple[RouteArgumentResult, ...]:
        """Invoke per-route writers only after every route is locally READY."""
        self._validate_output_routes(output_routes)
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
            llm_result = self._writer.invoke(
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

    def compose(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
    ) -> tuple[RouteArgumentResult, ...]:
        """Legacy production entry point; retained unchanged until atomic cut-over."""
        self._validate_output_routes(output_routes)
        results: list[RouteArgumentResult] = []
        for route in output_routes:
            bound_schema = self._bound_schema(route)
            llm_result = self._writer.invoke(
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

    def revise(
        self,
        *,
        request: WorkflowStartRequest,
        request_intent: RequestIntentV2,
        output_routes: tuple[OutputToolRouteV1, ...],
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
        plan_draft: ActionPlanDraftV1,
        review_issues: list[ReviewIssueV1],
        review_summary: str | None,
    ) -> tuple[RouteArgumentResult, ...]:
        """Revise only affected per-route candidates under frozen route identity."""
        self._validate_output_routes(output_routes)
        write_actions = [action for action in plan_draft["actions"] if action["effect"] != "READ"]
        if len(write_actions) != len(output_routes):
            raise ValueError(
                "planning revision requires exactly one existing write action per frozen output route"
            )
        allowed_evidence_refs = {draft["evidence_id"] for draft in evidence_drafts}
        results: list[RouteArgumentResult] = []
        for route, action in zip(output_routes, write_actions, strict=True):
            if (
                action["tool_name"] != route["selected_tool_id"]
                or action["effect"] != route["effect"]
            ):
                raise ValueError(
                    f"existing plan action no longer aligns with frozen output route: {route['route_id']}"
                )
            bound_schema = self._bound_schema(route)
            candidate = validate_tool_argument_candidate_v1(
                {
                    "schema_version": 1,
                    "route_id": route["route_id"],
                    "arguments": dict(action["arguments"]),
                    "evidence_refs": list(action["evidence_refs"]),
                },
                bound_tool_schema=bound_schema,
                allowed_evidence_refs=allowed_evidence_refs,
            )
            relevant_issues = _issues_for_action(review_issues, action_id=action["action_id"])
            if not relevant_issues:
                results.append(RouteArgumentResult(route, bound_schema, candidate, None))
                continue
            llm_result = self._writer.revise(
                request=request,
                request_intent=request_intent,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
                analysis_result=analysis_result,
                candidate_output=candidate,
                review_issues=relevant_issues,
                review_summary=review_summary,
            )
            revised_candidate = self._writer.validated_candidate(
                llm_result,
                bound_tool_schema=bound_schema,
                evidence_drafts=evidence_drafts,
            )
            results.append(RouteArgumentResult(route, bound_schema, revised_candidate, llm_result))
        return tuple(results)

    def _prepare_route(self, route: OutputToolRouteV1) -> PlanningActionPreparationResultV1:
        try:
            bound_schema = self._bound_schema(route)
        except RequiredContainerUnresolvedError:
            return {
                "disposition": "NEEDS_CONFIRMATION",
                "route_id": route["route_id"],
                "question": "Select the required destination container for this action.",
                "options": [],
                "reason_codes": ["PLANNING_REQUIRED_CONTAINER_UNRESOLVED"],
            }
        except PlanningArgumentBindingError:
            return {
                "disposition": "BLOCKED",
                "route_id": route["route_id"],
                "reason_codes": ["PLAN_ARGUMENT_CONSTRAINT_VIOLATION"],
            }
        return {
            "disposition": "READY",
            "route_id": route["route_id"],
            "bound_tool_schema": bound_schema,
        }

    def _bound_schema(self, route: OutputToolRouteV1) -> BoundSelectedToolSchemaV1:
        explicit_container_id = (
            self._explicit_container_provider(route)
            if self._explicit_container_provider is not None
            else None
        )
        return self._default_container_resolver.bind_selected_tool_schema(
            route=route,
            selected_tool_schema=planning_tool_argument_schema(route["selected_tool_id"]),
            explicit_container_id=explicit_container_id,
        )

    @staticmethod
    def _validate_output_routes(output_routes: tuple[OutputToolRouteV1, ...]) -> None:
        if not output_routes:
            raise ValueError("ACTION planning requires at least one frozen output route")
        route_ids = [route["route_id"] for route in output_routes]
        if len(route_ids) != len(set(route_ids)):
            raise ValueError("duplicate output route id")


def validate_planning_action_preparation_result_v1(
    value: object,
) -> PlanningActionPreparationResultV1:
    if not isinstance(value, Mapping):
        raise ValueError("PlanningActionPreparationResultV1 must be an object")
    root = dict(value)
    disposition = root.get("disposition")
    route_id = root.get("route_id")
    if not isinstance(route_id, str) or not route_id:
        raise ValueError("PlanningActionPreparationResultV1.route_id is required")
    if disposition == "READY":
        if set(root) != {"disposition", "route_id", "bound_tool_schema"}:
            raise ValueError("READY preparation keys are invalid")
        if not isinstance(root["bound_tool_schema"], Mapping):
            raise ValueError("READY preparation requires bound_tool_schema")
        return cast(PlanningActionPreparationReadyV1, root)
    if disposition == "NEEDS_CONFIRMATION":
        if set(root) != {"disposition", "route_id", "question", "options", "reason_codes"}:
            raise ValueError("NEEDS_CONFIRMATION preparation keys are invalid")
        if not isinstance(root["question"], str) or not root["question"]:
            raise ValueError("NEEDS_CONFIRMATION question is required")
        _string_list(root["options"], allow_empty=True)
        _string_list(root["reason_codes"], allow_empty=False)
        return cast(PlanningActionPreparationNeedsConfirmationV1, root)
    if disposition in {"ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"}:
        if set(root) != {"disposition", "route_id", "reason_codes"}:
            raise ValueError("non-ready preparation keys are invalid")
        _string_list(root["reason_codes"], allow_empty=False)
        return cast(PlanningActionPreparationResultV1, root)
    raise ValueError("PlanningActionPreparationResultV1.disposition is invalid")


def project_planning_action_confirmation_required_v1(
    preparation: PlanningActionPreparationResultV1,
    *,
    interrupt_id: str,
    resume_target: AgentNodeResumeTargetV2,
) -> ConfirmationRequiredV1:
    preparation = validate_planning_action_preparation_result_v1(preparation)
    if preparation["disposition"] != "NEEDS_CONFIRMATION":
        raise ValueError("Planning confirmation projection requires NEEDS_CONFIRMATION")
    if not interrupt_id:
        raise ValueError("interrupt_id is required")
    if resume_target.semantic_owner_id != "PLANNING":
        raise ValueError("Planning confirmation must resume PLANNING")
    return {
        "kind": "CONFIRMATION_REQUIRED",
        "interrupt_id": interrupt_id,
        "semantic_owner_id": "PLANNING",
        "resume_target": resume_target,
        "question": preparation["question"],
        "options": list(preparation["options"]),
    }


def _string_list(value: object, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("expected a list of non-empty strings")
    result = cast(list[str], list(value))
    if not allow_empty and not result:
        raise ValueError("string list must not be empty")
    if len(result) != len(set(result)):
        raise ValueError("string list contains duplicates")
    return result


def _issues_for_action(
    review_issues: list[ReviewIssueV1], *, action_id: str
) -> list[ReviewIssueV1]:
    result: list[ReviewIssueV1] = []
    for issue in review_issues:
        affected_action_ids = issue.get("affected_action_ids", [])
        if not affected_action_ids or action_id in affected_action_ids:
            result.append(issue)
    return result


__all__ = [
    "PlanningActionPreparationResultV1",
    "PlanningArgumentOrchestrator",
    "RouteArgumentResult",
    "project_planning_action_confirmation_required_v1",
    "validate_planning_action_preparation_result_v1",
]
