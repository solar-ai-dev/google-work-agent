"""Pure policy validation helpers for deterministic application rules."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.domain.action.model import PolicyViolationError


@dataclass(frozen=True, slots=True)
class EvidencePolicyInput:
    """Inputs needed to validate evidence minimum and update targeting rules."""

    evidence_count: int
    requires_existing_resource: bool
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
    """Enforce the documented evidence minimum and update safety rules."""

    if policy_input.evidence_count < 1:
        raise PolicyViolationError("every action requires at least one evidence")

    if not policy_input.requires_existing_resource:
        return

    if policy_input.has_user_selected_resource:
        return

    if policy_input.has_explicit_resource_relation:
        return

    if policy_input.evidence_count >= 2:
        return

    raise PolicyViolationError(
        "existing resource updates require a user-selected target, "
        "two evidences, or one explicit resource relation"
    )


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
