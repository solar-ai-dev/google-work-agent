from pathlib import Path

from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceGatewayError,
    ResourceType,
)
from tests.support.fakes import FakeGoogleGateway, GoogleGatewayFault, GoogleGatewayFaultKind
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "data" / "google"


def _gateway() -> FakeGoogleGateway:
    snapshot = ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot(
        "workspace/product_fixture_v1.json"
    )
    return FakeGoogleGateway(snapshot)


def test_fake_google__gateway_returns_deterministic__reads_and_pagination() -> None:
    gateway = _gateway()

    first = gateway.search_gmail_threads(query="", page_token=None, page_size=1)
    second = gateway.search_gmail_threads(query="", page_token=None, page_size=1)
    page_two = gateway.search_gmail_threads(
        query="",
        page_token=first.next_page_token,
        page_size=1,
    )

    assert first == second
    assert len(first.items) == 1
    assert first.next_page_token == "1"
    assert page_two.items[0].resource_id == "thread-project"


def test_fake_google_gateway__create_and_update__support_followup_get() -> None:
    gateway = _gateway()

    created_task = gateway.create_task(
        task_list_id="task-list-default",
        payload={"resource_id": "task-new", "title": "Write summary", "status": "needsAction"},
    )
    fetched_task = gateway.get_task(task_list_id="task-list-default", task_id="task-new")
    updated_task = gateway.update_task(
        task_list_id="task-list-default",
        task_id="task-new",
        payload={"notes": "Include blockers"},
    )
    fetched_updated_task = gateway.get_task(task_list_id="task-list-default", task_id="task-new")

    assert created_task.resource_id == "task-new"
    assert fetched_task.payload["title"] == "Write summary"
    assert updated_task.version == "2"
    assert fetched_updated_task.payload["notes"] == "Include blockers"


def test_fake_google_gateway__before_delivery_fault__does_not_mutate() -> None:
    gateway = _gateway()
    gateway.queue_fault(
        operation="create_gmail_draft",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY),
    )

    try:
        gateway.create_gmail_draft(payload={"resource_id": "draft-timeout", "subject": "Oops"})
    except GoogleWorkspaceGatewayError as error:
        assert error.delivered is False
        assert error.mutated is False
    else:
        raise AssertionError("expected gateway timeout before delivery")

    try:
        gateway.get_gmail_draft(draft_id="draft-timeout")
    except LookupError:
        pass
    else:
        raise AssertionError("draft should not have been created")


def test_fake_google_gateway__after_delivery_fault__mutates_and_supports_recovery() -> None:
    gateway = _gateway()
    gateway.queue_fault(
        operation="create_calendar_event",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.RESPONSE_LOST_AFTER_MUTATION),
    )

    try:
        gateway.create_calendar_event(
            calendar_id="calendar-primary",
            payload={
                "resource_id": "event-created",
                "title": "Created despite lost response",
                "recovery_fingerprint": "rf-created-event",
            },
        )
    except GoogleWorkspaceGatewayError as error:
        assert error.delivered is True
        assert error.mutated is True
    else:
        raise AssertionError("expected response-lost gateway fault")

    recovered = gateway.get_calendar_event(calendar_id="calendar-primary", event_id="event-created")
    matches = gateway.search_by_recovery_fingerprint(
        resource_type=ResourceType.CALENDAR_EVENT,
        recovery_fingerprint="rf-created-event",
    )

    assert recovered.payload["title"] == "Created despite lost response"
    assert [item.resource_id for item in matches] == ["event-created"]


def test_fake_google_gateway__can_emit_verification__mismatch_and_version_change() -> None:
    gateway = _gateway()
    gateway.queue_fault(
        operation="get_calendar_event",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.VERIFICATION_MISMATCH),
    )
    mismatched = gateway.get_calendar_event(calendar_id="calendar-primary", event_id="event-focus")

    gateway.queue_fault(
        operation="get_calendar_event",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.RESOURCE_VERSION_CHANGED),
    )
    changed = gateway.get_calendar_event(calendar_id="calendar-primary", event_id="event-focus")

    assert mismatched.payload["title"].endswith(" (mismatch)")
    assert changed.version == "8"


def test_fake_google_gateway__recovery_duplicate_and__no_candidate_faults() -> None:
    gateway = _gateway()
    gateway.queue_fault(
        operation="search_by_recovery_fingerprint",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.DUPLICATE_RECOVERY_CANDIDATE),
    )
    duplicates = gateway.search_by_recovery_fingerprint(
        resource_type=ResourceType.CALENDAR_EVENT,
        recovery_fingerprint="anything",
    )
    assert len(duplicates) == 2

    gateway.queue_fault(
        operation="search_by_recovery_fingerprint",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.NO_RECOVERY_CANDIDATE),
    )
    none_found = gateway.search_by_recovery_fingerprint(
        resource_type=ResourceType.CALENDAR_EVENT,
        recovery_fingerprint="anything",
    )
    assert none_found == ()
