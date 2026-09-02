from __future__ import annotations

from json import loads

from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)


def test_audit_event_redacts__secret_like_metadata__keys_but_keeps_ids() -> None:
    record = _audit_event(
        run_id="run-1",
        action_id="action-1",
        event_type="WRITE_APPROVED",
        outcome="TRANSITION_APPLIED",
        metadata={
            "refresh_token": "ya29.super-secret-refresh-token",
            "access_token": "ya29.super-secret-access-token",
            "api_key": "sk-super-secret-api-key",
            "claim_token": "claim.super-secret-token",
            "client_secret": "gocspx-super-secret",
            "Authorization": "Bearer super-secret-header-value",
            "command_id": "command-1",
            "correlation_id": "correlation-1",
            "approval_id": "approval-1",
            "decision": "APPROVED",
        },
        created_at_ms=1000,
    )

    metadata = loads(record.metadata_json)

    for forbidden_key in (
        "refresh_token",
        "access_token",
        "api_key",
        "claim_token",
        "client_secret",
        "Authorization",
    ):
        assert forbidden_key not in metadata
    raw_json = record.metadata_json
    assert "super-secret" not in raw_json

    assert metadata["command_id"] == "command-1"
    assert metadata["correlation_id"] == "correlation-1"
    assert metadata["approval_id"] == "approval-1"
    assert metadata["decision"] == "APPROVED"
    assert record.run_id == "run-1"
    assert record.action_id == "action-1"
