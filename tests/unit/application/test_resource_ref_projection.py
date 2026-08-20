from json import loads

from google_work_agent.application.resource_ref_projection import resource_ref_from_snapshot
from google_work_agent.ports import ResourceSnapshot, ResourceType


def _snapshot(resource_type: ResourceType, payload: dict[str, object]) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="fixture-1",
        resource_type=resource_type,
        resource_id="resource-1",
        parent_id="parent-1",
        related_resource_ids=(),
        version="v1",
        recovery_fingerprint=None,
        payload=payload,
    )


def test_write_resource_ref_does_not_persist_raw_provider_payload() -> None:
    snapshot = _snapshot(
        ResourceType.TASK,
        {
            "title": "Ship report",
            "status": "needsAction",
            "due": "2026-08-21",
            "notes": "private long body",
            "page_token": "provider-secret-page-token",
            "access_token": "provider-access-token",
            "unknown_provider_blob": {"nested": "must not persist"},
        },
    )

    resource_ref = resource_ref_from_snapshot(
        run_id="run-1",
        snapshot=snapshot,
        captured_at_ms=10,
    )

    assert loads(resource_ref.metadata_json) == {
        "due": "2026-08-21",
        "status": "needsAction",
    }
    assert resource_ref.title == "Ship report"
    assert resource_ref.version_token == "v1"
    assert "provider-secret-page-token" not in resource_ref.metadata_json
    assert "provider-access-token" not in resource_ref.metadata_json
    assert "private long body" not in resource_ref.metadata_json


def test_message_metadata_is_bounded_to_existing_read_projection_fields() -> None:
    snapshot = _snapshot(
        ResourceType.GMAIL_MESSAGE,
        {
            "subject": "Status",
            "from": "sender@example.com",
            "to": ["a@example.com", "b@example.com"],
            "attachments": [{"id": "a1"}],
            "body": "must not persist",
            "raw": "must not persist",
        },
    )

    resource_ref = resource_ref_from_snapshot(
        run_id="run-1",
        snapshot=snapshot,
        captured_at_ms=10,
    )

    assert loads(resource_ref.metadata_json) == {
        "attachment_count": 1,
        "from": "sender@example.com",
        "to_count": 2,
    }
    assert resource_ref.title == "Status"
    assert "body" not in resource_ref.metadata_json
    assert "raw" not in resource_ref.metadata_json
