from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
    normalize_resource_type,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.validate_route import (
    ToolRouteValidationError,
)
from google_work_agent.application.prompt_runtime.contracts.failure_record import (
    build_failure_record_v1,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    default_prompt_manifest_path,
    load_prompt_reference,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    merge_provider_dispatch_usage,
    provider_dispatch_budget_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    RunBudgetV2,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.domain.action.model import EffectType
from google_work_agent.ports.llm.structured_inference_contracts import (
    OutputSchemaDefinition,
    PromptReference,
)
from google_work_agent.ports.llm.structured_inference_port import StructuredInferencePort
from google_work_agent.ports.system.contracts.confirmation import (
    ConfirmationResponseProjectionV1,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowStartRequest

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


def determine_io_resources(
    *,
    llm_runtime: StructuredInferencePort,
    tool_catalog: SignedToolRegistry,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
    retry_budget: RunBudgetV2,
    prompt_ref: PromptReference | None = None,
    manifest_path: Path | None = None,
    confirmation_response: ConfirmationResponseProjectionV1 | None = None,
) -> tuple[SemanticRouteCandidate, RunBudgetV2]:
    resolved_prompt_ref = prompt_ref or load_prompt_reference(
        "tool_routing.determine_io_resources",
        manifest_path or default_prompt_manifest_path(),
    )
    base_projection: dict[str, object] = {
        "request_intent": request_intent,
        "eligible_route_capabilities": _eligible_route_capabilities(tool_catalog),
    }
    if confirmation_response is not None:
        base_projection["confirmation_response"] = dict(confirmation_response)
    with provider_dispatch_budget_scope(retry_budget):
        result = llm_runtime.infer(
            request.requested_mode,
            resolved_prompt_ref,
            base_projection,
            ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA,
        )
        try:
            raw = _validate_candidate(result.structured_output)
        except ToolRouteValidationError as error:
            failure_code = "SEMANTIC_CANDIDATE_INVALID"
            signature = build_semantic_failure_signature_v1(
                node_id="route.determine_resources", failure_reason_codes=[failure_code]
            )
            decision = approve_semantic_revision(retry_budget, signature=signature)
            if decision["decision"] == BudgetDecision.DENY.value:
                raise ToolRouteValidationError(
                    "tool route semantic candidate revision denied: "
                    "same failure signature already used"
                ) from error
            revised = llm_runtime.infer(
                request.requested_mode,
                resolved_prompt_ref,
                {
                    "base_projection": dict(base_projection),
                    "candidate_output": result.structured_output,
                    "failure_record": build_failure_record_v1(
                        failure_reason_code=failure_code,
                        failure_origin="LLM_OUTPUT",
                        detected_by="RUNTIME_DOMAIN_VALIDATOR",
                        runtime_disposition="RETRYABLE",
                        experiment_disposition="RUN_REVISION",
                        affected_field_paths=[
                            "$.input_resource_types",
                            "$.output_resource_types",
                            "$.output_effects",
                            "$.disposition",
                        ],
                        failure_context_ids=[str(error)],
                    ),
                },
                ROUTE_RESOURCE_CANDIDATE_OUTPUT_SCHEMA,
            )
            raw = _validate_candidate(revised.structured_output)
            retry_budget = decision["run_budget"]
        if raw["disposition"] in {"NEEDS_CONFIRMATION", "BLOCKED"}:
            raise ToolRouteValidationError(
                f"tool route semantic candidate is not ready: {raw['disposition']}"
            )
        return _semantic_candidate(
            raw,
            request_intent=request_intent,
            request=request,
        ), merge_provider_dispatch_usage(retry_budget)


def _semantic_candidate(
    raw: Mapping[str, object],
    *,
    request_intent: RequestIntentV2,
    request: WorkflowStartRequest,
) -> SemanticRouteCandidate:
    inferred_input_resources = tuple(
        dict.fromkeys(
            normalize_resource_type(cast(str, item))
            for item in cast(list[object], raw["input_resource_types"])
        )
    )
    selected_input_resources = _selected_input_resource_types(request)
    if selected_input_resources and {
        coarse_resource_category(resource) for resource in selected_input_resources
    } != {coarse_resource_category(resource) for resource in inferred_input_resources}:
        raise ToolRouteValidationError(
            "RESOURCE_SELECTED input scope does not match the semantic route candidate"
        )
    input_resources = selected_input_resources or inferred_input_resources
    raw_output_resources = cast(list[str], raw["output_resource_types"])
    output_effects = tuple(
        EffectType(cast(str, item)) for item in cast(list[object], raw["output_effects"])
    )
    if not raw_output_resources or raw["disposition"] == "NO_TOOL_NEEDED":
        output_mode: Literal["ANSWER", "ACTION"] = "ANSWER"
        output_pairs: tuple[tuple[str, EffectType], ...] = ()
    else:
        output_mode = "ACTION"
        if len(output_effects) == 1:
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, output_effects[0]), output_effects[0])
                for resource in raw_output_resources
            )
        elif len(output_effects) == len(raw_output_resources):
            output_pairs = tuple(
                (_normalize_output_resource_type(resource, effect), effect)
                for resource, effect in zip(raw_output_resources, output_effects, strict=True)
            )
        else:
            raise ToolRouteValidationError("resource/effect candidate cardinality is ambiguous")
    analysis_requirement = request_intent.get("analysis_requirement", "REQUIRED")
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise ToolRouteValidationError("analysis_requirement is invalid")
    return SemanticRouteCandidate(
        input_resource_types=input_resources,
        output_pairs=output_pairs,
        output_mode=output_mode,
        analysis_requirement=cast(Literal["NONE", "REQUIRED"], analysis_requirement),
    )


def _selected_input_resource_types(request: WorkflowStartRequest) -> tuple[str, ...]:
    if request.entry_mode != "RESOURCE_SELECTED":
        return ()
    mapping = {
        ("GMAIL", "THREAD"): "GMAIL_THREAD",
        ("GMAIL", "MESSAGE"): "GMAIL_MESSAGE",
        ("GMAIL", "DRAFT"): "GMAIL_DRAFT",
        ("GMAIL", "ATTACHMENT"): "GMAIL_ATTACHMENT",
        ("TASKS", "TASK_LIST"): "TASK_LIST",
        ("TASKS", "TASK"): "TASK",
        ("CALENDAR", "CALENDAR"): "CALENDAR",
        ("CALENDAR", "EVENT"): "CALENDAR_EVENT",
        ("CALENDAR", "FREEBUSY"): "CALENDAR_FREEBUSY",
    }
    try:
        return tuple(
            dict.fromkeys(
                mapping[(resource.source, resource.resource_type)]
                for resource in request.selected_resources
            )
        )
    except KeyError as error:
        raise ToolRouteValidationError(
            "RESOURCE_SELECTED contains an unsupported resource identity"
        ) from error


def _validate_candidate(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolRouteValidationError("RouteResourceCandidateV1 must be an object")
    root = cast(Mapping[str, object], value)
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


def _eligible_route_capabilities(tool_catalog: SignedToolRegistry) -> list[dict[str, object]]:
    by_key: dict[tuple[str, str], dict[str, object]] = {}
    for entry in tool_catalog.entries:
        connector_id = entry.connector_id
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
    if coarse_resource == "EMAIL":
        if effect is EffectType.SEND:
            return "GMAIL_MESSAGE"
        if effect in {EffectType.CREATE, EffectType.UPDATE}:
            return "GMAIL_DRAFT"
    return normalize_resource_type(coarse_resource)
