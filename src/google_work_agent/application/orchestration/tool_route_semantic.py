"""Tool Route semantic LLM stage.

Owns PromptRef resolution, prompt input projection, LLM invocation, and
semantic-candidate/tool-selection validation for Tool Route. Never assembles
a final ``ToolRoutePlanV2`` and never binds a Registry tool on its own
authority -- ``ToolRouteCoordinator`` (tool_routing.py) keeps sole ownership
of deterministic registry binding, PolicyPreconditionResolver, validation,
and freezing. This module supplies that coordinator with a
``SemanticRouteCandidate`` and, only when the Registry has more than one
eligible tool for a route, a Registry-validated tool selection.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from google_work_agent.application.llm import StructuredLLMRuntime
from google_work_agent.ports.observability_events import ObservabilityContext
from google_work_agent.application.orchestration.contracts import (
    BudgetDecision,
    ConfirmationResponseProjectionV1,
    RunBudgetV1,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.orchestration.failure_record import build_failure_record_v1
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2
from google_work_agent.application.orchestration.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.orchestration.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.orchestration.provider_dispatch_budget import (
    legacy_post_call_projection,
    provider_dispatch_budget_scope,
)
from google_work_agent.application.orchestration.tool_routing import (
    SemanticRouteCandidate,
    ToolRouteValidationError,
    coarse_resource_category,
    normalize_resource_type,
)
from google_work_agent.domain import ConnectorToolCatalog, EffectType
from google_work_agent.ports import (
    OutputSchemaDefinition,
    PromptReference,
    WorkflowStartRequest,
)


def load_tool_route_determine_io_resources_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "tool_route.determine_io_resources",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_tool_route_select_tool_if_needed_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "tool_route.select_tool_if_needed",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_tool_route_determine_io_resources_revision_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "tool_route.determine_io_resources.revise",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_tool_route_select_tool_if_needed_revision_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "tool_route.select_tool_if_needed.revise",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="route-resource-candidate-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "input_resource_types",
            "output_resource_types",
            "output_effects",
            "disposition",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "input_resource_types": {
                "type": "array",
                "items": {"enum": ["EMAIL", "TASK", "CALENDAR"]},
                "uniqueItems": True,
            },
            "output_resource_types": {
                "type": "array",
                "items": {"enum": ["EMAIL", "TASK", "CALENDAR"]},
                "uniqueItems": True,
            },
            "output_effects": {
                "type": "array",
                "items": {"enum": ["CREATE", "UPDATE", "SEND", "DELETE"]},
            },
            "disposition": {
                "enum": ["ROUTE_READY", "NO_TOOL_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"]
            },
        },
    },
)

TOOL_SELECTION_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="tool-selection-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "route_id", "selected_tool_id"],
        "properties": {
            "schema_version": {"const": 1},
            "route_id": {"type": "string"},
            "selected_tool_id": {"type": "string"},
        },
    },
)


class ToolRouteAgent:
    """Own the Tool Route semantic candidate LLM stage.

    Registry authority stays with ``ToolRouteCoordinator``: this Agent only
    produces a semantic resource/effect candidate and, when the Registry
    has more than one eligible tool for a route, a selection among those
    Registry-validated candidates. It never assembles a final
    ``ToolRoutePlanV2``.
    """

    def __init__(
        self,
        *,
        llm_runtime: StructuredLLMRuntime,
        tool_catalog: ConnectorToolCatalog,
        prompt_ref: PromptReference | None = None,
        select_tool_prompt_ref: PromptReference | None = None,
        determine_io_resources_revision_prompt_ref: PromptReference | None = None,
        select_tool_revision_prompt_ref: PromptReference | None = None,
        manifest_path: Path | None = None,
    ) -> None:
        self._llm_runtime = llm_runtime
        self._tool_catalog = tool_catalog
        self._prompt_ref = (
            prompt_ref or load_tool_route_determine_io_resources_prompt_reference(manifest_path)
        )
        self._select_tool_prompt_ref = (
            select_tool_prompt_ref
            or load_tool_route_select_tool_if_needed_prompt_reference(manifest_path)
        )
        self._determine_io_resources_revision_prompt_ref = (
            determine_io_resources_revision_prompt_ref
            or load_tool_route_determine_io_resources_revision_prompt_reference(manifest_path)
        )
        self._select_tool_revision_prompt_ref = (
            select_tool_revision_prompt_ref
            or load_tool_route_select_tool_if_needed_revision_prompt_reference(manifest_path)
        )

    @property
    def prompt_ref(self) -> PromptReference:
        return self._prompt_ref

    def determine_semantic_candidate(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        retry_budget: RunBudgetV1,
        confirmation_response: ConfirmationResponseProjectionV1 | None = None,
    ) -> tuple[SemanticRouteCandidate, RunBudgetV1]:
        with provider_dispatch_budget_scope(retry_budget):
            return self._determine_semantic_candidate_scoped(
                request_intent=request_intent,
                request=request,
                retry_budget=retry_budget,
                confirmation_response=confirmation_response,
            )

    def _determine_semantic_candidate_scoped(
        self,
        *,
        request_intent: RequestIntentV2,
        request: WorkflowStartRequest,
        retry_budget: RunBudgetV1,
        confirmation_response: ConfirmationResponseProjectionV1 | None,
    ) -> tuple[SemanticRouteCandidate, RunBudgetV1]:
        eligible_route_capabilities = _eligible_route_capabilities(self._tool_catalog)
        base_projection: dict[str, object] = {
            "request_intent": request_intent,
            "eligible_route_capabilities": eligible_route_capabilities,
        }
        if confirmation_response is not None:
            base_projection["confirmation_response"] = dict(confirmation_response)
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._prompt_ref,
            prompt_input=base_projection,
            output_schema=ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:tool_route.determine_io_resources",
            ),
        )
        try:
            candidate = _validate_route_resource_candidate(llm_result.structured_output)
        except ToolRouteValidationError as error:
            candidate, retry_budget = self._revise_semantic_candidate_once(
                base_projection=base_projection,
                request=request,
                previous_output=llm_result.structured_output,
                failure_detail=str(error),
                retry_budget=retry_budget,
            )
        if candidate["disposition"] in {"NEEDS_CONFIRMATION", "BLOCKED"}:
            raise ToolRouteValidationError(
                f"tool route semantic candidate is not ready: {candidate['disposition']}"
            )
        return (
            _semantic_candidate_from_llm_candidate(candidate, request_intent=request_intent),
            legacy_post_call_projection(retry_budget),
        )

    def _revise_semantic_candidate_once(
        self,
        *,
        base_projection: dict[str, object],
        request: WorkflowStartRequest,
        previous_output: object,
        failure_detail: str,
        retry_budget: RunBudgetV1,
    ) -> tuple[Mapping[str, object], RunBudgetV1]:
        """Bounded semantic revision using the frozen runtime envelope."""
        failure_code = "SEMANTIC_CANDIDATE_INVALID"
        signature = build_semantic_failure_signature_v1(
            node_id="tool_route.determine_io_resources",
            failure_reason_codes=[failure_code],
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            raise ToolRouteValidationError(
                "tool route semantic candidate revision denied: "
                "same failure signature already used"
            )
        mutable_fields = [
            "$.input_resource_types",
            "$.output_resource_types",
            "$.output_effects",
            "$.disposition",
        ]
        revision_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._determine_io_resources_revision_prompt_ref,
            prompt_input={
                "base_projection": dict(base_projection),
                "candidate_output": previous_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code=failure_code,
                    failure_origin="LLM_OUTPUT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=mutable_fields,
                    failure_context_ids=[failure_detail],
                ),
            },
            output_schema=ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:tool_route.determine_io_resources.semantic_revision",
            ),
        )
        return (
            _validate_route_resource_candidate(revision_result.structured_output),
            decision["run_budget"],
        )

    def select_tool_if_needed(
        self,
        *,
        route_id: str,
        connector_id: str,
        resource_type: str,
        effect: str,
        eligible_tool_ids: tuple[str, ...],
        request: WorkflowStartRequest,
        retry_budget: RunBudgetV1,
    ) -> tuple[str, RunBudgetV1]:
        with provider_dispatch_budget_scope(retry_budget):
            return self._select_tool_if_needed_scoped(
                route_id=route_id,
                connector_id=connector_id,
                resource_type=resource_type,
                effect=effect,
                eligible_tool_ids=eligible_tool_ids,
                request=request,
                retry_budget=retry_budget,
            )

    def _select_tool_if_needed_scoped(
        self,
        *,
        route_id: str,
        connector_id: str,
        resource_type: str,
        effect: str,
        eligible_tool_ids: tuple[str, ...],
        request: WorkflowStartRequest,
        retry_budget: RunBudgetV1,
    ) -> tuple[str, RunBudgetV1]:
        prompt_input = {
            "route_id": route_id,
            "connector_id": connector_id,
            "resource_type": resource_type,
            "effect": effect,
            "eligible_tool_ids": list(eligible_tool_ids),
        }
        llm_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_tool_prompt_ref,
            prompt_input=prompt_input,
            output_schema=TOOL_SELECTION_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:tool_route.select_tool_if_needed",
            ),
        )
        selected_tool_id = self._validated_tool_selection(
            llm_result.structured_output, eligible_tool_ids=eligible_tool_ids
        )
        if selected_tool_id is not None:
            return selected_tool_id, legacy_post_call_projection(retry_budget)
        failure_code = "TOOL_SELECTION_INVALID"
        signature = build_semantic_failure_signature_v1(
            node_id="tool_route.select_tool_if_needed",
            failure_reason_codes=[failure_code],
        )
        decision = approve_semantic_revision(retry_budget, signature=signature)
        if decision["decision"] == BudgetDecision.DENY.value:
            raise ToolRouteValidationError(
                "tool selection revision denied: same failure signature already used"
            )
        mutable_fields = ["$.selected_tool_id"]
        revision_result = self._llm_runtime.invoke_structured(
            prompt_ref=self._select_tool_revision_prompt_ref,
            prompt_input={
                "base_projection": dict(prompt_input),
                "candidate_output": llm_result.structured_output,
                "failure_record": build_failure_record_v1(
                    failure_reason_code=failure_code,
                    failure_origin="LLM_OUTPUT",
                    detected_by="RUNTIME_DOMAIN_VALIDATOR",
                    runtime_disposition="RETRYABLE",
                    experiment_disposition="RUN_REVISION",
                    affected_field_paths=mutable_fields,
                    failure_context_ids=[
                        "selected_tool_id is not a Registry-eligible candidate"
                    ],
                ),
            },
            output_schema=TOOL_SELECTION_OUTPUT_SCHEMA,
            trace_context=ObservabilityContext(
                request_id=request.correlation.request_id,
                command_id=request.correlation.command_id,
                conversation_id=request.conversation_id,
                run_id=request.run_id,
                langgraph_thread_id=request.workflow_key,
                llm_call_id=f"{request.run_id}:tool_route.select_tool_if_needed.semantic_revision",
            ),
        )
        revised_tool_id = self._validated_tool_selection(
            revision_result.structured_output, eligible_tool_ids=eligible_tool_ids
        )
        if revised_tool_id is None:
            raise ToolRouteValidationError(
                "selected tool is not a Registry-eligible candidate after revision"
            )
        return revised_tool_id, legacy_post_call_projection(decision["run_budget"])

    def _validated_tool_selection(
        self, value: object, *, eligible_tool_ids: tuple[str, ...]
    ) -> str | None:
        selection = _validate_tool_selection(value)
        selected_tool_id = selection["selected_tool_id"]
        if selected_tool_id not in eligible_tool_ids:
            return None
        return cast(str, selected_tool_id)


def _validate_route_resource_candidate(value: object) -> Mapping[str, object]:
    root = _mapping(value, "$")
    if root.get("schema_version") != 1:
        raise ToolRouteValidationError("RouteResourceCandidateV1.schema_version must be 1")
    for field in ("input_resource_types", "output_resource_types"):
        items = root.get(field)
        if not isinstance(items, list) or any(
            item not in {"EMAIL", "TASK", "CALENDAR"} for item in items
        ):
            raise ToolRouteValidationError(f"RouteResourceCandidateV1.{field} is invalid")
    effects = root.get("output_effects")
    if not isinstance(effects, list) or any(
        item not in {"CREATE", "UPDATE", "SEND", "DELETE"} for item in effects
    ):
        raise ToolRouteValidationError("RouteResourceCandidateV1.output_effects is invalid")
    if root.get("disposition") not in {
        "ROUTE_READY",
        "NO_TOOL_NEEDED",
        "NEEDS_CONFIRMATION",
        "BLOCKED",
    }:
        raise ToolRouteValidationError("RouteResourceCandidateV1.disposition is invalid")
    return root


def _validate_tool_selection(value: object) -> Mapping[str, object]:
    root = _mapping(value, "$")
    if root.get("schema_version") != 1:
        raise ToolRouteValidationError("ToolSelectionV1.schema_version must be 1")
    _string(root, "route_id")
    _string(root, "selected_tool_id")
    return root


def _eligible_route_capabilities(
    tool_catalog: ConnectorToolCatalog,
) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for connector_id in tool_catalog.list_connector_ids():
        for entry in tool_catalog.registry_for(connector_id).list_entries():
            category = coarse_resource_category(entry.resource_type)
            capability = by_key.setdefault(
                (connector_id, category),
                {
                    "connector_id": connector_id,
                    "resource_type": category,
                    "read_supported": False,
                    "write_effects": [],
                },
            )
            if entry.effect_type is EffectType.READ:
                capability["read_supported"] = True
            else:
                write_effects = cast(list[str], capability["write_effects"])
                if entry.effect_type.value not in write_effects:
                    write_effects.append(entry.effect_type.value)
    return list(by_key.values())


def _normalize_output_resource_type(coarse_resource: str, effect: EffectType) -> str:
    """Expand a coarse output resource type using its paired effect."""
    if coarse_resource == "EMAIL":
        if effect is EffectType.SEND:
            return "GMAIL_MESSAGE"
        if effect in {EffectType.CREATE, EffectType.UPDATE}:
            return "GMAIL_DRAFT"
    return normalize_resource_type(coarse_resource)


def _semantic_candidate_from_llm_candidate(
    candidate: Mapping[str, object],
    *,
    request_intent: RequestIntentV2,
) -> SemanticRouteCandidate:
    input_resource_types = tuple(
        dict.fromkeys(
            normalize_resource_type(cast(str, item))
            for item in cast(list[str], candidate["input_resource_types"])
        )
    )
    raw_output_resource_types = cast(list[str], candidate["output_resource_types"])
    output_effects = tuple(
        EffectType(item) for item in cast(list[str], candidate["output_effects"])
    )
    if not raw_output_resource_types or candidate["disposition"] == "NO_TOOL_NEEDED":
        output_mode: Literal["ANSWER", "ACTION"] = "ANSWER"
        output_pairs: tuple[tuple[str, EffectType], ...] = ()
    else:
        output_mode = "ACTION"
        if len(output_effects) == 1:
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, output_effects[0]), output_effects[0])
                for resource in raw_output_resource_types
            )
        elif len(output_effects) == len(raw_output_resource_types):
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, effect), effect)
                for resource, effect in zip(
                    raw_output_resource_types, output_effects, strict=True
                )
            )
        else:
            raise ToolRouteValidationError("resource/effect candidate cardinality is ambiguous")
    analysis_requirement = cast(
        Literal["NONE", "REQUIRED"],
        request_intent.get("analysis_requirement", "REQUIRED"),
    )
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise ToolRouteValidationError("analysis_requirement is invalid")
    return SemanticRouteCandidate(
        input_resource_types=input_resource_types,
        output_pairs=output_pairs,
        output_mode=output_mode,
        analysis_requirement=analysis_requirement,
    )


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolRouteValidationError(f"{path} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ToolRouteValidationError(f"{key} must be a non-empty string")
    return item


__all__ = [
    "ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA",
    "TOOL_SELECTION_OUTPUT_SCHEMA",
    "ToolRouteAgent",
    "load_tool_route_determine_io_resources_prompt_reference",
    "load_tool_route_select_tool_if_needed_prompt_reference",
]
