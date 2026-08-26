from dataclasses import replace

import pytest

from google_work_agent.domain.action.model import PolicyViolationError
from google_work_agent.domain.policy import (
    ApprovalIntegrityInput,
    EvidencePolicyInput,
    validate_approval_integrity,
    validate_evidence_policy,
)


def test_evidence_policy_requires_at_least_one_evidence() -> None:
    with pytest.raises(PolicyViolationError, match="at least one evidence"):
        validate_evidence_policy(
            EvidencePolicyInput(
                evidence_count=0,
                requires_existing_resource=False,
            )
        )


def test_evidence_policy_allows_existing_resource_update_with_two_evidences() -> None:
    validate_evidence_policy(
        EvidencePolicyInput(
            evidence_count=2,
            requires_existing_resource=True,
        )
    )


def test_evidence_policy_allows_existing_resource_update_with_user_selected_target() -> None:
    validate_evidence_policy(
        EvidencePolicyInput(
            evidence_count=1,
            requires_existing_resource=True,
            has_user_selected_resource=True,
        )
    )


def test_evidence_policy_blocks_under_evidenced_existing_resource_update() -> None:
    with pytest.raises(PolicyViolationError, match="existing resource updates require"):
        validate_evidence_policy(
            EvidencePolicyInput(
                evidence_count=1,
                requires_existing_resource=True,
            )
        )


def test_approval_integrity_accepts_matching_fresh_snapshot() -> None:
    validate_approval_integrity(
        ApprovalIntegrityInput(
            approval_arguments_hash="a" * 64,
            current_arguments_hash="a" * 64,
            approval_source_snapshot_hash="b" * 64,
            current_source_snapshot_hash="b" * 64,
            approval_action_version=3,
            current_action_version=3,
            approval_policy_version="2026-08-06.p0",
            current_policy_version="2026-08-06.p0",
            approval_tool_schema_version="v1",
            current_tool_schema_version="v1",
            now_ms=100,
            expires_at_ms=101,
        )
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"current_arguments_hash": "c" * 64}, "arguments hash"),
        ({"current_source_snapshot_hash": "d" * 64}, "source snapshot hash"),
        ({"current_action_version": 4}, "action version"),
        ({"current_policy_version": "2026-08-07.p0"}, "policy version"),
        ({"current_tool_schema_version": "v2"}, "tool schema version"),
        ({"now_ms": 101}, "expired"),
    ],
)
def test_approval_integrity_rejects_mismatch_and_expiry(
    overrides: dict[str, str | int],
    message: str,
) -> None:
    base = ApprovalIntegrityInput(
        approval_arguments_hash="a" * 64,
        current_arguments_hash="a" * 64,
        approval_source_snapshot_hash="b" * 64,
        current_source_snapshot_hash="b" * 64,
        approval_action_version=3,
        current_action_version=3,
        approval_policy_version="2026-08-06.p0",
        current_policy_version="2026-08-06.p0",
        approval_tool_schema_version="v1",
        current_tool_schema_version="v1",
        now_ms=100,
        expires_at_ms=101,
    )

    if "current_arguments_hash" in overrides:
        candidate = replace(base, current_arguments_hash=str(overrides["current_arguments_hash"]))
    elif "current_source_snapshot_hash" in overrides:
        candidate = replace(
            base,
            current_source_snapshot_hash=str(overrides["current_source_snapshot_hash"]),
        )
    elif "current_action_version" in overrides:
        candidate = replace(base, current_action_version=int(overrides["current_action_version"]))
    elif "current_policy_version" in overrides:
        candidate = replace(base, current_policy_version=str(overrides["current_policy_version"]))
    elif "current_tool_schema_version" in overrides:
        candidate = replace(
            base,
            current_tool_schema_version=str(overrides["current_tool_schema_version"]),
        )
    else:
        candidate = replace(base, now_ms=int(overrides["now_ms"]))

    with pytest.raises(PolicyViolationError, match=message):
        validate_approval_integrity(candidate)
