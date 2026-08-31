"""Deterministic Stage 11 domain-validation helpers."""

from __future__ import annotations

from evaluation.compat.solution_planning import (
    SolutionPlanningValidationError,
    validate_action_plan_draft_v1,
)
from evaluation.compat.work_analysis_result_v1 import (
    WorkAnalysisResultV1,
)
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationOutputV1,
    DomainValidationResult,
    validate_domain_validation_output_v1,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    ActionPlanDraftV1,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import (
    SignedToolRegistry,
)
from google_work_agent.domain.action.model import EffectType


class DomainValidationValidationError(ValueError):
    """Raised when a domain-validation output is structurally invalid."""


class DomainValidationService:
    """Deterministic Stage 11 domain-validation service."""

    def __init__(self, *, tool_registry: SignedToolRegistry | None = None) -> None:
        self._tool_registry = tool_registry or load_signed_tool_registry()

    def __call__(
        self,
        *,
        plan_draft: ActionPlanDraftV1,
        analysis_result: WorkAnalysisResultV1,
    ) -> DomainValidationOutputV1:
        return build_domain_validation_output_v1(
            plan_draft=plan_draft,
            analysis_result=analysis_result,
            tool_registry=self._tool_registry,
        )


def build_domain_validation_output_v1(
    *,
    plan_draft: ActionPlanDraftV1,
    analysis_result: WorkAnalysisResultV1,
    tool_registry: SignedToolRegistry | None = None,
) -> DomainValidationOutputV1:
    registry = tool_registry or load_signed_tool_registry()
    try:
        validated_plan = validate_action_plan_draft_v1(
            plan_draft,
            analysis_result=analysis_result,
            tool_registry=registry,
        )
    except SolutionPlanningValidationError:
        return validate_domain_validation_output_v1(
            {
                "schema_version": 1,
                "result": DomainValidationResult.BLOCK.value,
                "reason_codes": ["PLAN_DRAFT_INVALID"],
                "blocked_action_ids": [],
            }
        )

    action_effects = {EffectType(action["effect"]) for action in validated_plan["actions"]}
    if action_effects <= {EffectType.READ}:
        result = DomainValidationResult.ALLOW_READ
        reason_codes = ["READ_ONLY_PLAN"]
    else:
        result = DomainValidationResult.REQUIRE_APPROVAL
        reason_codes = ["WRITE_EFFECT_PRESENT"]

    return validate_domain_validation_output_v1(
        {
            "schema_version": 1,
            "result": result.value,
            "reason_codes": reason_codes,
            "blocked_action_ids": [],
        }
    )


def validate_domain_validation_service_output_v1(
    value: object,
) -> DomainValidationOutputV1:
    try:
        return validate_domain_validation_output_v1(value)
    except ValueError as error:
        raise DomainValidationValidationError(str(error)) from error


__all__ = [
    "DomainValidationService",
    "DomainValidationValidationError",
    "build_domain_validation_output_v1",
    "validate_domain_validation_service_output_v1",
]
