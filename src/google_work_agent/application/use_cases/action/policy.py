"""Action-owner-local deterministic policy validation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from google_work_agent.application.use_cases.action.evaluate_action_policy import (
    _evaluate_evidence_policy,
)
from google_work_agent.domain.action.model import PolicyViolationError


@dataclass(frozen=True, slots=True)
class EvidencePolicyInput:
    """Inputs needed to validate evidence minimum and update targeting rules."""

    evidence_count: int
    requires_existing_resource: bool
    independent_evidence_count: int = 0
    has_user_selected_resource: bool = False
    has_explicit_resource_relation: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalIntegrityInput:
    """Inputs needed to validate approval freshness and integrity."""

    approval_arguments_hash: str
    current_arguments_hash: str
    approval_source_snapshot_hash: str
    current_source_snapshot_hash: str
    approval_action_version: int
    current_action_version: int
    approval_policy_version: str
    current_policy_version: str
    approval_tool_schema_version: str
    current_tool_schema_version: str
    now_ms: int
    expires_at_ms: int


def validate_evidence_policy(policy_input: EvidencePolicyInput) -> None:
    """Project owner call-site facts through the single policy evaluator."""

    result = _evaluate_evidence_policy(
        evidence_count=policy_input.evidence_count,
        independent_evidence_count=policy_input.independent_evidence_count,
        requires_existing_resource=policy_input.requires_existing_resource,
        target_is_user_selected=policy_input.has_user_selected_resource,
        has_explicit_resource_relation=policy_input.has_explicit_resource_relation,
    )
    if result is not None:
        raise PolicyViolationError(result[1])


def count_independent_evidence(evidence: Iterable[object]) -> int:
    """Count distinct source authorities, not duplicate excerpts from one source."""

    identities: set[tuple[object, ...]] = set()
    for item in evidence:
        origin_type = getattr(item, "origin_type", None)
        resource_ref_id = getattr(item, "resource_ref_id", None)
        message_id = getattr(item, "message_id", None)
        if resource_ref_id is not None or message_id is not None:
            identities.add((origin_type, resource_ref_id, message_id))
            continue
        identities.add(
            (
                origin_type,
                getattr(item, "locator_json", None),
                getattr(item, "kind", None),
                getattr(item, "excerpt", None),
            )
        )
    return len(identities)


def validate_approval_integrity(policy_input: ApprovalIntegrityInput) -> None:
    """Enforce approval hash, source, version, and TTL integrity."""

    if policy_input.approval_arguments_hash != policy_input.current_arguments_hash:
        raise PolicyViolationError("approval arguments hash does not match current arguments")

    if policy_input.approval_source_snapshot_hash != policy_input.current_source_snapshot_hash:
        raise PolicyViolationError("approval source snapshot hash does not match current source")

    if policy_input.approval_action_version != policy_input.current_action_version:
        raise PolicyViolationError("approval action version does not match current action version")

    if policy_input.approval_policy_version != policy_input.current_policy_version:
        raise PolicyViolationError("approval policy version does not match current policy version")

    if policy_input.approval_tool_schema_version != policy_input.current_tool_schema_version:
        raise PolicyViolationError(
            "approval tool schema version does not match current tool schema version"
        )

    if policy_input.now_ms >= policy_input.expires_at_ms:
        raise PolicyViolationError("approval has expired")
