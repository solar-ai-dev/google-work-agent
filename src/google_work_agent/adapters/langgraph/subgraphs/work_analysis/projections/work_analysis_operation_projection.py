"""Allowlisted projection of one Work Analysis operation input."""

from __future__ import annotations

from collections.abc import Mapping

_ALLOWED = frozenset({"extract_work_facts", "resolve_entity_relations", "resolve_temporal_dependencies", "detect_duplicate_conflict_candidates", "validate_relations", "assess_information_gaps", "assess_operational_risks", "assemble_work_analysis", "validate_work_analysis"})


def project_work_analysis_operation_input(state: Mapping[str, object], operation: str) -> dict[str, object]:
    if operation not in _ALLOWED:
        raise ValueError(f"unknown work analysis operation: {operation}")
    inputs = state.get("operation_inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("work analysis operation_inputs are required")
    value = inputs.get(operation)
    if not isinstance(value, Mapping):
        raise ValueError(f"missing typed input projection for work_analysis.{operation}")
    return dict(value)
