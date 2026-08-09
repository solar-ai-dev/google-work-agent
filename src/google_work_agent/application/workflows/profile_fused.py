"""Profile-specific fused prompt contracts for Stage 18 native profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.api_acquisition import (
    SourcePlanningOutputV1,
    validate_source_fetch_plans_v1,
)
from google_work_agent.application.workflows.context_retrieval import (
    ContextRetrievalResultV1,
    validate_context_retrieval_result_v1,
)
from google_work_agent.application.workflows.plan_review import (
    load_plan_review_inspect_prompt_reference,
    validate_plan_review_result_v1,
)
from google_work_agent.application.workflows.prompt_registry import (
    default_prompt_manifest_path as _registry_default_prompt_manifest_path,
)
from google_work_agent.application.workflows.prompt_registry import (
    load_prompt_reference as _load_registry_prompt_reference,
)
from google_work_agent.application.workflows.request_understanding import (
    RequestIntentV1,
    validate_request_intent_v1,
)
from google_work_agent.application.workflows.solution_planning import (
    ActionPlanDraftV1,
    AnswerDraftV1,
    validate_action_plan_draft_v1,
    validate_answer_draft_v1,
)
from google_work_agent.application.workflows.work_analysis import (
    WorkAnalysisResultV1,
    validate_work_analysis_result_v1,
)
from google_work_agent.ports import OutputSchemaDefinition, PromptReference


class ProfilePlanningProjectionV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: Literal["ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"]
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None


class ProfileRequestSourceOutputV1(TypedDict):
    schema_version: Required[Literal[2]]
    request_intent: RequestIntentV1
    source_plan: SourcePlanningOutputV1


class ProfileReasonPlanOutputV1(TypedDict):
    schema_version: Required[Literal[2]]
    context_result: ContextRetrievalResultV1
    analysis_result: WorkAnalysisResultV1
    planning_result: ProfilePlanningProjectionV1


PROFILE_REQUEST_SOURCE_SCHEMA_VERSION: Final = 2
PROFILE_FUSED_PLANNING_SCHEMA_VERSION: Final = 2
PROFILE_PLANNING_PROJECTION_SCHEMA_VERSION: Final = 2


class ProfileFusedValidationError(ValueError):
    """Raised when a profile-fused prompt result is invalid."""


PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="profile-request-source-output-v2",
    json_schema={
        "type": "object",
        "required": ["schema_version", "request_intent", "source_plan"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "integer",
                "enum": [PROFILE_REQUEST_SOURCE_SCHEMA_VERSION],
            },
            "request_intent": {"type": "object"},
            "source_plan": {"type": "object"},
        },
    },
)

PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="profile-fused-planning-output-v2",
    json_schema={
        "type": "object",
        "required": [
            "schema_version",
            "context_result",
            "analysis_result",
            "planning_result",
        ],
        "additionalProperties": False,
        "properties": {
            "schema_version": {
                "type": "integer",
                "enum": [PROFILE_FUSED_PLANNING_SCHEMA_VERSION],
            },
            "context_result": {"type": "object"},
            "analysis_result": {"type": "object"},
            "planning_result": {
                "type": "object",
                "required": ["schema_version", "status", "answer_draft", "plan_draft"],
                "additionalProperties": False,
                "properties": {
                    "schema_version": {
                        "type": "integer",
                        "enum": [PROFILE_PLANNING_PROJECTION_SCHEMA_VERSION],
                    },
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


def load_profile_single_request_source_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.single.request_source.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_single_reason_plan_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.single.reason_plan.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_single_self_review_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.single.self_review.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_single_self_review_recheck_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.single.self_review.recheck",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_three_stage1_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.three.stage1.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_three_stage2_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return _load_registry_prompt_reference(
        "profile.three.stage2.initial",
        manifest_path or _registry_default_prompt_manifest_path(),
    )


def load_profile_three_stage3_prompt_reference(
    manifest_path: Path | None = None,
) -> PromptReference:
    return load_plan_review_inspect_prompt_reference(
        manifest_path or _registry_default_prompt_manifest_path()
    )


def validate_profile_request_source_output_v1(value: object) -> ProfileRequestSourceOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(root, "$", {"schema_version", "request_intent", "source_plan"})
    _require_schema_version(root, "$", PROFILE_REQUEST_SOURCE_SCHEMA_VERSION)
    request_intent = validate_request_intent_v1(root["request_intent"])
    source_plan = _validate_source_planning_output_v1(root["source_plan"])
    return {
        "schema_version": PROFILE_REQUEST_SOURCE_SCHEMA_VERSION,
        "request_intent": request_intent,
        "source_plan": source_plan,
    }


def validate_profile_reason_plan_output_v1(value: object) -> ProfileReasonPlanOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {"schema_version", "context_result", "analysis_result", "planning_result"},
    )
    _require_schema_version(root, "$", PROFILE_FUSED_PLANNING_SCHEMA_VERSION)
    context_result = validate_context_retrieval_result_v1(root["context_result"])
    analysis_result = validate_work_analysis_result_v1(
        root["analysis_result"],
        context_result=context_result,
    )
    planning_result = validate_profile_planning_projection_v1(
        root["planning_result"],
        analysis_result=analysis_result,
    )
    return {
        "schema_version": PROFILE_FUSED_PLANNING_SCHEMA_VERSION,
        "context_result": context_result,
        "analysis_result": analysis_result,
        "planning_result": planning_result,
    }


def validate_profile_planning_projection_v1(
    value: object,
    *,
    analysis_result: WorkAnalysisResultV1,
) -> ProfilePlanningProjectionV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {"schema_version", "status", "answer_draft", "plan_draft"},
    )
    _require_schema_version(root, "$", PROFILE_PLANNING_PROJECTION_SCHEMA_VERSION)
    status = _require_string(root, "status", "$")
    if status not in {"ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"}:
        raise ProfileFusedValidationError("$.status is invalid")
    answer_draft = (
        None
        if root["answer_draft"] is None
        else validate_answer_draft_v1(root["answer_draft"], analysis_result=analysis_result)
    )
    plan_draft = (
        None
        if root["plan_draft"] is None
        else validate_action_plan_draft_v1(root["plan_draft"], analysis_result=analysis_result)
    )
    result: ProfilePlanningProjectionV1 = {
        "schema_version": PROFILE_PLANNING_PROJECTION_SCHEMA_VERSION,
        "status": cast(
            Literal["ANSWER_ONLY", "PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
            status,
        ),
        "answer_draft": answer_draft,
        "plan_draft": plan_draft,
    }
    _validate_profile_planning_projection_invariant(result)
    return result


def _validate_profile_planning_projection_invariant(
    result: ProfilePlanningProjectionV1,
) -> None:
    status = result["status"]
    answer_draft = result["answer_draft"]
    plan_draft = result["plan_draft"]
    if status == "ANSWER_ONLY":
        if answer_draft is None or plan_draft is not None:
            raise ProfileFusedValidationError(
                "ANSWER_ONLY requires answer_draft and forbids plan_draft"
            )
        return
    if status == "PLAN_READY":
        if plan_draft is None or answer_draft is not None:
            raise ProfileFusedValidationError(
                "PLAN_READY requires plan_draft and forbids answer_draft"
            )
        return
    if status == "NEEDS_CONFIRMATION":
        if answer_draft is not None and answer_draft["status"] != "NEEDS_CONFIRMATION":
            raise ProfileFusedValidationError(
                "NEEDS_CONFIRMATION answer_draft must carry NEEDS_CONFIRMATION status"
            )
        if plan_draft is not None and plan_draft["status"] != "NEEDS_CONFIRMATION":
            raise ProfileFusedValidationError(
                "NEEDS_CONFIRMATION plan_draft must carry NEEDS_CONFIRMATION status"
            )
        if answer_draft is None and plan_draft is None:
            raise ProfileFusedValidationError(
                "NEEDS_CONFIRMATION requires either answer_draft or plan_draft"
            )
        return
    if answer_draft is not None and answer_draft["status"] != "BLOCKED":
        raise ProfileFusedValidationError("BLOCKED answer_draft must carry BLOCKED status")
    if plan_draft is not None and plan_draft["status"] != "BLOCKED":
        raise ProfileFusedValidationError("BLOCKED plan_draft must carry BLOCKED status")
    if answer_draft is None and plan_draft is None:
        raise ProfileFusedValidationError("BLOCKED requires either answer_draft or plan_draft")


def _validate_source_planning_output_v1(value: object) -> SourcePlanningOutputV1:
    root = _require_mapping(value, "$")
    _require_exact_keys(
        root,
        "$",
        {
            "schema_version",
            "result",
            "source_fetch_plans",
            "clarification",
            "failure",
            "validator_codes",
        },
        optional={"llm_provider_result"},
    )
    _require_schema_version(root, "$", 1)
    result = _require_string(root, "result", "$")
    if result not in {"PLAN_READY", "NO_FETCH_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"}:
        raise ProfileFusedValidationError("$.result is invalid")
    source_fetch_plans = root["source_fetch_plans"]
    if not isinstance(source_fetch_plans, list):
        raise ProfileFusedValidationError("$.source_fetch_plans must be a list")
    clarification = root["clarification"]
    if clarification is not None and not isinstance(clarification, dict):
        raise ProfileFusedValidationError("$.clarification must be object or null")
    failure = root["failure"]
    if failure is not None and not isinstance(failure, dict):
        raise ProfileFusedValidationError("$.failure must be object or null")
    validator_codes = _require_string_list(root["validator_codes"], "$.validator_codes")
    typed: SourcePlanningOutputV1 = {
        "schema_version": 1,
        "result": cast(
            Literal["PLAN_READY", "NO_FETCH_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"],
            result,
        ),
        "source_fetch_plans": validate_source_fetch_plans_v1(source_fetch_plans),
        "clarification": cast(dict[str, object] | None, clarification),
        "failure": cast(dict[str, object] | None, failure),
        "validator_codes": validator_codes,
        "llm_provider_result": {},
    }
    if "llm_provider_result" in root:
        provider_result = root["llm_provider_result"]
        if not isinstance(provider_result, dict):
            raise ProfileFusedValidationError("$.llm_provider_result must be an object")
        typed["llm_provider_result"] = cast(dict[str, object], provider_result)
    return typed


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ProfileFusedValidationError(f"{path} must be an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ProfileFusedValidationError(f"{path} keys must be strings")
        result[key] = item
    return result


def _require_exact_keys(
    value: dict[str, object],
    path: str,
    required: set[str],
    *,
    optional: set[str] | None = None,
) -> None:
    optional_keys = optional or set()
    keys = set(value)
    missing = sorted(required - keys)
    unknown = sorted(keys - required - optional_keys)
    if missing:
        raise ProfileFusedValidationError(f"{path} missing required keys: {missing}")
    if unknown:
        raise ProfileFusedValidationError(f"{path} contains unsupported keys: {unknown}")


def _require_schema_version(value: dict[str, object], path: str, expected: int) -> None:
    schema_version = value.get("schema_version")
    if schema_version != expected:
        raise ProfileFusedValidationError(f"{path}.schema_version must be {expected}")


def _require_string(value: dict[str, object], field: str, path: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ProfileFusedValidationError(f"{path}.{field} must be a non-empty string")
    return item


def _require_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise ProfileFusedValidationError(f"{path} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ProfileFusedValidationError(f"{path}[{index}] must be a non-empty string")
        result.append(item)
    return result


__all__ = [
    "ProfileFusedValidationError",
    "PROFILE_FUSED_PLANNING_OUTPUT_SCHEMA",
    "PROFILE_REQUEST_SOURCE_OUTPUT_SCHEMA",
    "ProfilePlanningProjectionV1",
    "ProfileReasonPlanOutputV1",
    "ProfileRequestSourceOutputV1",
    "load_profile_single_reason_plan_prompt_reference",
    "load_profile_single_request_source_prompt_reference",
    "load_profile_single_self_review_prompt_reference",
    "load_profile_single_self_review_recheck_prompt_reference",
    "load_profile_three_stage1_prompt_reference",
    "load_profile_three_stage2_prompt_reference",
    "load_profile_three_stage3_prompt_reference",
    "validate_profile_planning_projection_v1",
    "validate_profile_reason_plan_output_v1",
    "validate_profile_request_source_output_v1",
    "validate_plan_review_result_v1",
]
