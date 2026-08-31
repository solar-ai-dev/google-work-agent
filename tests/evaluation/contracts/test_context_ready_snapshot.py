from __future__ import annotations

import pytest
from evaluation.contracts.context_ready_snapshot import (
    ContextReadySnapshotV1,
    EvaluationPolicyProjectionV1,
)
from pydantic import ValidationError


def test_context_ready_snapshot_is_gold_free_and_stable() -> None:
    snapshot = ContextReadySnapshotV1(
        schema_version=1,
        context_snapshot_id="context-1",
        source_case_id="CASE-CORE-001",
        fixture_snapshot_id="FW-CORE-001",
        request_intent={"goal": "read selected mail"},
        context_bundle={"resource_refs": ["mail-1"]},
        evidence_set=[{"evidence_id": "evidence-1"}],
        policy_projection=EvaluationPolicyProjectionV1(
            schema_version=1,
            source_case_id="CASE-CORE-001",
            policy_summary={"write_allowed": False},
        ),
    )

    payload = snapshot.model_dump(mode="json")
    assert "gold" not in payload
    assert (
        snapshot.stable_hash()
        == ContextReadySnapshotV1.model_validate(payload, strict=True).stable_hash()
    )


def test_context_ready_snapshot_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        EvaluationPolicyProjectionV1.model_validate(
            {
                "schema_version": 1,
                "source_case_id": "CASE-CORE-001",
                "policy_summary": {},
                "policy_decision": "ALLOW",
            },
            strict=True,
        )
