"""Shared deterministic Plan Aggregate structural validation."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class PlanEvidenceDraft(Protocol):
    """Minimal evidence shape required by the aggregate validator."""

    @property
    def evidence_id(self) -> str: ...


class PlanActionDraft(Protocol):
    """Minimal action shape required by the aggregate validator."""

    @property
    def action_id(self) -> str: ...
    @property
    def position(self) -> int: ...
    @property
    def evidence_ids(self) -> tuple[str, ...]: ...
    @property
    def depends_on_action_ids(self) -> tuple[str, ...]: ...


def validate_plan_structure(
    *,
    actions: Sequence[PlanActionDraft],
    evidence: Sequence[PlanEvidenceDraft],
    plan_label: str,
) -> None:
    """Fail closed on malformed action/evidence/dependency graphs before persistence."""
    if not actions:
        raise ValueError(f"{plan_label} requires at least one action")

    action_ids = {item.action_id for item in actions}
    if len(action_ids) != len(actions):
        raise ValueError(f"duplicate action_id in {plan_label}")

    positions = {item.position for item in actions}
    if len(positions) != len(actions):
        raise ValueError(f"duplicate action position in {plan_label}")

    evidence_ids = {item.evidence_id for item in evidence}
    if len(evidence_ids) != len(evidence):
        raise ValueError(f"duplicate evidence_id in {plan_label}")

    adjacency: dict[str, tuple[str, ...]] = {}
    for action in actions:
        if not action.evidence_ids:
            raise ValueError(f"action requires evidence: {action.action_id}")
        if len(set(action.evidence_ids)) != len(action.evidence_ids):
            raise ValueError(f"duplicate action evidence link: {action.action_id}")
        for evidence_id in action.evidence_ids:
            if evidence_id not in evidence_ids:
                raise LookupError(f"action references missing evidence: {evidence_id}")

        if len(set(action.depends_on_action_ids)) != len(action.depends_on_action_ids):
            raise ValueError(f"duplicate action dependency: {action.action_id}")
        for depends_on_action_id in action.depends_on_action_ids:
            if depends_on_action_id == action.action_id:
                raise ValueError("action cannot depend on itself")
            if depends_on_action_id not in action_ids:
                raise LookupError(f"action dependency not found: {depends_on_action_id}")
        adjacency[action.action_id] = action.depends_on_action_ids

    _validate_no_dependency_cycle(adjacency)


def _validate_no_dependency_cycle(adjacency: dict[str, tuple[str, ...]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def _visit(node: str) -> None:
        if node in visited:
            return
        if node in visiting:
            raise ValueError("action dependency cycle detected")
        visiting.add(node)
        for dependency in adjacency[node]:
            _visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in adjacency:
        _visit(node)
