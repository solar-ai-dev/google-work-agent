"""Typed Product Prompt runtime-input contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

PROMPT_RUNTIME_INPUT_CONTRACT_SCHEMA_VERSION: Final = 1

REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT: Final[dict[str, str]] = {
    "request_understanding.identify_goal": "request.identify_goal",
    "request_understanding.detect_ambiguity": "request.detect_ambiguity",
    "tool_routing.determine_io_resources": "route.determine_resources",
    "tool_routing.select_tool_if_needed": "route.select_tool",
    "retrieval.plan_query": "retrieval.plan_query",
    "retrieval.select_evidence": "retrieval.select_evidence",
    "retrieval.assess_sufficiency": "retrieval.assess_sufficiency",
    "work_analysis.extract_work_facts": "analysis.extract_facts",
    "work_analysis.resolve_entity_relations": "analysis.resolve_entity_relations",
    "work_analysis.resolve_temporal_dependencies": "analysis.resolve_temporal_dependencies",
    "work_analysis.detect_duplicate_conflict_candidates": (
        "analysis.detect_duplicate_conflict_candidates"
    ),
    "work_analysis.assess_information_gaps": "analysis.assess_information_gaps",
    "work_analysis.assess_operational_risks": "analysis.assess_operational_risks",
    "planning.outline_answer": "planning.outline_answer",
    "planning.compose_answer": "planning.compose_answer",
    "planning.draft_action_objective_per_output_route": (
        "planning.draft_action_objective_per_output_route"
    ),
    "planning.compose_arguments_per_output_route": ("planning.compose_arguments_per_output_route"),
    "review.inspect_goal_and_evidence": "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route": "review.inspect_action_scope_route",
    "review.inspect_constraints_and_policy_summary": "review.inspect_constraints_policy",
    "review.recheck_affected_dimensions": "review.recheck",
}

REQUIRED_PROMPT_SLOT_IDS: Final[frozenset[str]] = frozenset(REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT)


class PromptRuntimeInputContractError(ValueError):
    """Raised before Product Prompt assembly when a projection is not allowed."""


@dataclass(frozen=True, slots=True)
class PromptRuntimeInputContractEntryV1:
    prompt_slot_id: str
    runtime_node_id: str
    input_schema_version: int
    required_root_fields: tuple[str, ...]
    optional_root_fields: tuple[str, ...]
    output_schema_version: int

    def __post_init__(self) -> None:
        if not self.prompt_slot_id or not self.runtime_node_id:
            raise PromptRuntimeInputContractError("prompt slot and runtime node are required")
        if self.input_schema_version != 1 or self.output_schema_version != 1:
            raise PromptRuntimeInputContractError("prompt schema versions must be 1")
        required = set(self.required_root_fields)
        optional = set(self.optional_root_fields)
        if len(required) != len(self.required_root_fields):
            raise PromptRuntimeInputContractError("required_root_fields contains duplicates")
        if len(optional) != len(self.optional_root_fields):
            raise PromptRuntimeInputContractError("optional_root_fields contains duplicates")
        if required & optional:
            raise PromptRuntimeInputContractError(
                "required_root_fields and optional_root_fields overlap"
            )
        if not all(required | optional):
            raise PromptRuntimeInputContractError("prompt input field names must be non-empty")

    @property
    def allowed_root_fields(self) -> frozenset[str]:
        return frozenset((*self.required_root_fields, *self.optional_root_fields))


@dataclass(frozen=True, slots=True)
class PromptRuntimeInputContractV1:
    schema_version: int
    entries: tuple[PromptRuntimeInputContractEntryV1, ...]
    forbidden_input_fields: frozenset[str]
    _entries_by_slot: Mapping[str, PromptRuntimeInputContractEntryV1] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.schema_version != PROMPT_RUNTIME_INPUT_CONTRACT_SCHEMA_VERSION:
            raise PromptRuntimeInputContractError("prompt input-contract schema version must be 1")
        by_slot: dict[str, PromptRuntimeInputContractEntryV1] = {}
        for entry in self.entries:
            if entry.prompt_slot_id in by_slot:
                raise PromptRuntimeInputContractError(
                    f"duplicate prompt input-contract slot: {entry.prompt_slot_id}"
                )
            by_slot[entry.prompt_slot_id] = entry
        object.__setattr__(self, "_entries_by_slot", MappingProxyType(by_slot))

    @property
    def slot_ids(self) -> frozenset[str]:
        return frozenset(self._entries_by_slot)

    def entry(self, prompt_slot_id: str) -> PromptRuntimeInputContractEntryV1:
        try:
            return self._entries_by_slot[prompt_slot_id]
        except KeyError as error:
            raise PromptRuntimeInputContractError(
                f"unknown Product Prompt slot: {prompt_slot_id}"
            ) from error

    def validate_projection(
        self, prompt_slot_id: str, input_projection: Mapping[str, object]
    ) -> None:
        entry = self.entry(prompt_slot_id)
        actual = set(input_projection)
        missing = sorted(set(entry.required_root_fields) - actual)
        unknown = sorted(actual - entry.allowed_root_fields)
        if missing:
            raise PromptRuntimeInputContractError(
                f"missing required Product Prompt fields for {prompt_slot_id}: {missing}"
            )
        if unknown:
            raise PromptRuntimeInputContractError(
                f"unknown Product Prompt fields for {prompt_slot_id}: {unknown}"
            )
        violations = sorted(_find_forbidden_fields(input_projection, self.forbidden_input_fields))
        if violations:
            raise PromptRuntimeInputContractError(
                f"forbidden Product Prompt fields for {prompt_slot_id}: {violations}"
            )


def _find_forbidden_fields(value: object, forbidden: frozenset[str], path: str = "$") -> set[str]:
    violations: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}"
            if _normalize_field_name(key) in forbidden:
                violations.add(child_path)
            violations.update(_find_forbidden_fields(item, forbidden, child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            violations.update(_find_forbidden_fields(item, forbidden, f"{path}[{index}]"))
    return violations


def _normalize_field_name(value: str) -> str:
    return value.strip().lower().replace("-", "_")


__all__ = [
    "PROMPT_RUNTIME_INPUT_CONTRACT_SCHEMA_VERSION",
    "REQUIRED_PROMPT_RUNTIME_NODE_BY_SLOT",
    "REQUIRED_PROMPT_SLOT_IDS",
    "PromptRuntimeInputContractEntryV1",
    "PromptRuntimeInputContractError",
    "PromptRuntimeInputContractV1",
]
