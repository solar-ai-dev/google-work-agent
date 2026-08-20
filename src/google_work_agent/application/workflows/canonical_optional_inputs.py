"""Canonical optional-input helpers for SIX_ROLE Work Analysis and Planning.

Workflow v7.20 explicitly permits two production paths that the legacy V1
agents did not model:

* Tool Route may enter Work Analysis without a Retrieval invocation.
* Planning may run with no Work Analysis when effective analysis is not
  required, and may also receive Retrieval evidence directly without an
  analysis artifact.

These helpers preserve that absence as ``None``/empty evidence. They never
manufacture fake RetrievalResultV1 or WorkAnalysisResultV1 artifacts merely
to satisfy legacy function signatures.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import google_work_agent.application.workflows.solution_planning as _planning
import google_work_agent.application.workflows.work_analysis as _analysis
from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.application.observability import ObservabilityContext
from google_work_agent.application.workflows.handoff_contracts import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    ConfirmationResponseV1,
    EvidenceDraftV1,
    RequestIntentV2,
    WorkAnalysisResultV1,
)
from google_work_agent.application.workflows.planning_plan_assembler import (
    assemble_action_plan_draft_v2,
    materialize_action_seeds,
)
from google_work_agent.application.workflows.solution_planning import (
    ANSWER_DRAFT_OUTPUT_SCHEMA,
    SolutionPlanningAgent,
)
from google_work_agent.application.workflows.tool_routing import OutputToolRouteV1
from google_work_agent.application.workflows.work_analysis import (
    WORK_ANALYSIS_OUTPUT_SCHEMA,
    WorkAnalysisAgent,
)
from google_work_agent.application.write_verification_projection import (
    build_expected_verification_projection,
)
from google_work_agent.ports import StructuredLLMResult, WorkflowStartRequest


class CanonicalOptionalInputWorkAnalysisAgent(WorkAnalysisAgent):
    """Work Analysis entry point when no Retrieval invocation occurred."""

    def invoke_without_retrieval(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        policy_confirmation_receipt_refs: list[str],
        confirmation_response: ConfirmationResponseV1 | None = None,
    ) -> StructuredLLMResult:
        prompt_input: dict[str, object] = {
            "user_request": request.request_text,
            "request_intent": request_intent,
            "evidence": [],
            "availability_results": [],
            "policy_confirmation_receipt_refs": list(policy_confirmation_receipt_refs),
        }
        if confirmation_response is not None:
            prompt_input["confirmation_response"] = dict(confirmation_response)
        return self._llm_runtime.invoke_structured(
            prompt_ref=self.analyze_prompt_ref,
            prompt_input=prompt_input,
            output_schema=WORK_ANALYSIS_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:analysis.analyze",
            ),
            semantic_validate=validate_work_analysis_without_retrieval,
        )

    @staticmethod
    def build_without_retrieval(llm_result: StructuredLLMResult) -> WorkAnalysisResultV1:
        result = validate_work_analysis_without_retrieval(llm_result.structured_output)
        result["llm_provider_result"] = _analysis._provider_summary(llm_result)
        return result


class CanonicalOptionalInputPlanningAgent(SolutionPlanningAgent):
    """Planning answer entry point with optional Work Analysis."""

    def invoke_answer_with_optional_analysis(
        self,
        *,
        request_intent: RequestIntentV2,
        evidence_drafts: list[EvidenceDraftV1],
        analysis_result: WorkAnalysisResultV1 | None,
        request: WorkflowStartRequest,
        confirmation_response: ConfirmationResponseV1 | None = None,
    ) -> StructuredLLMResult:
        prompt_input: dict[str, object] = {
            "user_request": request.request_text,
            "request_intent": request_intent,
            "work_analysis": analysis_result,
            "evidence": planning_evidence_projection(evidence_drafts),
        }
        if confirmation_response is not None:
            prompt_input["confirmation_response"] = dict(confirmation_response)
        return self._llm_runtime.invoke_structured(
            prompt_ref=self.answer_only_prompt_ref,
            prompt_input=prompt_input,
            output_schema=ANSWER_DRAFT_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:planning.answer_only",
            ),
            semantic_validate=lambda candidate: validate_answer_with_optional_analysis(
                candidate,
                analysis_result=analysis_result,
                evidence_drafts=evidence_drafts,
            ),
        )

    @staticmethod
    def build_answer_with_optional_analysis(
        llm_result: StructuredLLMResult,
        *,
        analysis_result: WorkAnalysisResultV1 | None,
        evidence_drafts: list[EvidenceDraftV1],
    ) -> AnswerDraftV1:
        result = validate_answer_with_optional_analysis(
            llm_result.structured_output,
            analysis_result=analysis_result,
            evidence_drafts=evidence_drafts,
        )
        result["llm_provider_result"] = _planning._provider_summary(llm_result)
        return result


def validate_work_analysis_without_retrieval(value: object) -> WorkAnalysisResultV1:
    """Validate Work Analysis against an intentionally empty reference space."""

    return _analysis._validate_work_analysis_result_v1_core(
        value,
        refs={
            "evidence_ids": set(),
            "resource_handles": set(),
            "segment_ids": set(),
        },
    )


def validate_answer_with_optional_analysis(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1 | None,
    evidence_drafts: list[EvidenceDraftV1],
) -> AnswerDraftV1:
    """Validate an answer against supplied evidence plus optional analysis refs."""

    root = _planning._require_mapping(value, "$")
    _planning._require_allowed_keys(
        root,
        "$",
        required={
            "schema_version",
            "status",
            "answer",
            "evidence_refs",
            "resource_refs",
            "reason_codes",
            "confirmation",
            "blockers",
        },
        optional={"llm_provider_result"},
    )
    _planning._require_schema_version(root, "$", _planning.ANSWER_DRAFT_SCHEMA_VERSION)

    evidence_ids = {draft["evidence_id"] for draft in evidence_drafts}
    resource_handles = {
        draft["resource_handle"]
        for draft in evidence_drafts
        if isinstance(draft.get("resource_handle"), str) and draft["resource_handle"]
    }
    if analysis_result is not None:
        evidence_ids.update(analysis_result["evidence_refs"])
        resource_handles.update(
            str(ref["resource_handle"])
            for ref in analysis_result["resource_refs"]
            if isinstance(ref.get("resource_handle"), str)
        )
    refs = {
        "evidence_ids": evidence_ids,
        "resource_handles": resource_handles,
    }

    status = _planning._require_string(root, "status", "$")
    if status not in _planning._ANSWER_RESULT_VALUES:
        raise _planning.SolutionPlanningValidationError("$.status is invalid")
    result: AnswerDraftV1 = {
        "schema_version": _planning.ANSWER_DRAFT_SCHEMA_VERSION,
        "status": cast(_planning.AnswerDraftStatusValue, status),
        "answer": _planning._require_string(root, "answer", "$"),
        "evidence_refs": _planning._validated_evidence_refs(root["evidence_refs"], refs),
        "resource_refs": _planning._validated_resource_ref_objects(root["resource_refs"], refs),
        "reason_codes": _planning._require_string_list(root["reason_codes"], "$.reason_codes"),
        "confirmation": _planning._nullable_mapping(root["confirmation"], "$.confirmation"),
        "blockers": _planning._require_string_list(root["blockers"], "$.blockers"),
    }
    if "llm_provider_result" in root:
        result["llm_provider_result"] = _planning._require_mapping(
            root["llm_provider_result"], "$.llm_provider_result"
        )
    _planning._validate_answer_draft_invariant(result)
    return result


def assemble_plan_with_optional_analysis(
    *,
    request_intent: RequestIntentV2,
    analysis_result: WorkAnalysisResultV1 | None,
    evidence_drafts: list[EvidenceDraftV1],
    output_routes: tuple[OutputToolRouteV1, ...],
    argument_candidates: tuple[object, ...],
    plan_id_factory: callable,
    action_id_factory: callable,
    previous_plan: ActionPlanDraftV1 | None,
) -> ActionPlanDraftV1:
    """Assemble an ACTION plan without inventing a Work Analysis artifact."""

    if analysis_result is not None:
        return _planning_plan_with_analysis(
            request_intent=request_intent,
            analysis_result=analysis_result,
            evidence_drafts=evidence_drafts,
            output_routes=output_routes,
            argument_candidates=argument_candidates,
            plan_id_factory=plan_id_factory,
            action_id_factory=action_id_factory,
            previous_plan=previous_plan,
        )

    from google_work_agent.application.workflows.planning_arguments import (
        ToolArgumentCandidateV1,
    )

    candidates = cast(tuple[ToolArgumentCandidateV1, ...], argument_candidates)
    plan_id = previous_plan["plan_id"] if previous_plan is not None else plan_id_factory()
    if not isinstance(plan_id, str) or not plan_id:
        raise ValueError("plan id must not be empty")

    action_id_by_route: dict[str, str] | None = None
    if previous_plan is not None:
        write_actions = [
            action for action in previous_plan["actions"] if action["effect"] != "READ"
        ]
        if len(write_actions) != len(output_routes):
            raise ValueError("previous plan does not align with frozen output routes")
        action_id_by_route = {}
        for route, action in zip(output_routes, write_actions, strict=True):
            if (
                action["tool_name"] != route["selected_tool_id"]
                or action["effect"] != route["effect"]
            ):
                raise ValueError("previous action does not align with frozen output route")
            action_id_by_route[route["route_id"]] = action["action_id"]

    seeds = materialize_action_seeds(
        output_routes=output_routes,
        argument_candidates=candidates,
        action_id_factory=action_id_factory,
        action_id_by_route=action_id_by_route,
    )
    intent_meta = request_intent["meta"]
    canonical = assemble_action_plan_draft_v2(
        artifact_id=plan_id,
        revision=1,
        based_on=[
            {
                "artifact_id": intent_meta["artifact_id"],
                "revision": intent_meta["revision"],
            }
        ],
        action_seeds=seeds,
    )

    evidence_by_id = {draft["evidence_id"]: draft for draft in evidence_drafts}
    plan_evidence_refs = _stable_unique(
        evidence_ref
        for action in canonical["actions"]
        for evidence_ref in action["evidence_refs"]
    )
    resource_handles = _stable_unique(
        evidence_by_id[evidence_ref]["resource_handle"]
        for evidence_ref in plan_evidence_refs
        if evidence_ref in evidence_by_id
        and evidence_by_id[evidence_ref]["resource_handle"]
    )
    resource_refs = [{"resource_handle": handle} for handle in resource_handles]

    legacy_actions: list[dict[str, object]] = []
    for position, action in enumerate(canonical["actions"], start=1):
        action_resource_handles = _stable_unique(
            evidence_by_id[evidence_ref]["resource_handle"]
            for evidence_ref in action["evidence_refs"]
            if evidence_ref in evidence_by_id
            and evidence_by_id[evidence_ref]["resource_handle"]
        )
        legacy_actions.append(
            {
                "schema_version": 2,
                "action_id": action["action_id"],
                "position": position,
                "effect": action["effect"],
                "tool_name": action["tool_id"],
                "arguments": dict(action["arguments"]),
                "expected": build_expected_verification_projection(
                    tool_name=action["tool_id"], arguments=action["arguments"]
                ),
                "evidence_refs": list(action["evidence_refs"]),
                "resource_refs": action_resource_handles,
                "target_resource_ref_id": None,
                "depends_on_action_ids": list(action["depends_on_action_ids"]),
                "user_visible_reason": request_intent["goal"],
            }
        )

    return cast(
        ActionPlanDraftV1,
        {
            "schema_version": 2,
            "status": "PLAN_READY",
            "plan_id": plan_id,
            "summary": request_intent["goal"],
            "objective": request_intent["goal"],
            "actions": legacy_actions,
            "evidence_refs": plan_evidence_refs,
            "resource_refs": resource_refs,
            "confirmation": None,
        },
    )


def validate_plan_with_optional_analysis(
    value: ActionPlanDraftV1,
    *,
    analysis_result: WorkAnalysisResultV1 | None,
    evidence_drafts: list[EvidenceDraftV1],
    frozen_output_routes: tuple[OutputToolRouteV1, ...] | None,
    frozen_read_tool_ids: frozenset[str],
) -> ActionPlanDraftV1:
    """Revalidate code-assembled plans without fabricating Work Analysis."""

    if analysis_result is not None:
        return _planning.validate_action_plan_draft_v1(
            value,
            analysis_result=analysis_result,
            frozen_output_routes=frozen_output_routes,
            frozen_read_tool_ids=frozen_read_tool_ids,
        )

    # The no-analysis branch is code-assembled above; validate every reference
    # against actual supplied Evidence and then re-run the frozen-route guard.
    allowed_evidence = {draft["evidence_id"] for draft in evidence_drafts}
    allowed_resources = {
        draft["resource_handle"]
        for draft in evidence_drafts
        if draft["resource_handle"]
    }
    if any(ref not in allowed_evidence for ref in value["evidence_refs"]):
        raise _planning.SolutionPlanningValidationError(
            "plan evidence reference does not exist"
        )
    for resource_ref in value["resource_refs"]:
        handle = resource_ref.get("resource_handle")
        if not isinstance(handle, str) or handle not in allowed_resources:
            raise _planning.SolutionPlanningValidationError(
                "plan resource reference does not exist"
            )
    action_ids = {action["action_id"] for action in value["actions"]}
    if len(action_ids) != len(value["actions"]):
        raise _planning.SolutionPlanningValidationError("duplicate action_id in plan draft")
    for action in value["actions"]:
        if any(ref not in allowed_evidence for ref in action["evidence_refs"]):
            raise _planning.SolutionPlanningValidationError(
                "action evidence reference does not exist"
            )
        if any(ref not in allowed_resources for ref in action["resource_refs"]):
            raise _planning.SolutionPlanningValidationError(
                "action resource reference does not exist"
            )
        if any(dep not in action_ids for dep in action["depends_on_action_ids"]):
            raise _planning.SolutionPlanningValidationError(
                "action dependency not found"
            )
    _planning._validate_action_plan_invariant(value)
    if frozen_output_routes is not None:
        _planning._validate_frozen_output_routes(
            value,
            frozen_output_routes,
            frozen_read_tool_ids=frozen_read_tool_ids,
        )
    return value


def planning_evidence_projection(
    evidence_drafts: list[EvidenceDraftV1],
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


def _planning_plan_with_analysis(**kwargs: object) -> ActionPlanDraftV1:
    from google_work_agent.application.workflows.planning_plan_assembler import (
        assemble_action_plan_draft_v1_compat,
    )

    return assemble_action_plan_draft_v1_compat(**kwargs)  # type: ignore[arg-type]


def _stable_unique(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in cast(object, values):  # type: ignore[union-attr]
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


__all__ = [
    "CanonicalOptionalInputPlanningAgent",
    "CanonicalOptionalInputWorkAnalysisAgent",
    "assemble_plan_with_optional_analysis",
    "planning_evidence_projection",
    "validate_answer_with_optional_analysis",
    "validate_plan_with_optional_analysis",
    "validate_work_analysis_without_retrieval",
]
