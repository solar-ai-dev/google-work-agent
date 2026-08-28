from pathlib import Path

from google_work_agent.ports.connector.contracts.google_workspace import GoogleWorkspaceGatewayError
from tests.support.fakes import FakeGoogleGateway, GoogleGatewayFault, GoogleGatewayFaultKind
from tests.support.fixtures import ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "product"


def test_gateway_after_delivery_update_persists_state_even_when_response_is_lost() -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    gateway.queue_fault(
        operation="update_gmail_draft",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.CONNECTION_CLOSED_AFTER_DELIVERY),
    )

    try:
        gateway.update_gmail_draft(
            draft_id="draft-followup",
            payload={"body": "Updated body that should still persist."},
        )
    except GoogleWorkspaceGatewayError as error:
        assert error.delivered is True
        assert error.mutated is True
    else:
        raise AssertionError("expected connection-closed-after-delivery fault")

    draft = gateway.get_gmail_draft(draft_id="draft-followup")
    assert draft.payload["body"] == "Updated body that should still persist."


def test_gateway_before_delivery_timeout_keeps_state_unchanged() -> None:
    gateway = FakeGoogleGateway(
        ProductFixtureSnapshotLoader(FIXTURE_ROOT).load_snapshot("manifest.json")
    )
    original = gateway.get_task(task_list_id="task-list-default", task_id="task-followup")
    gateway.queue_fault(
        operation="update_task",
        fault=GoogleGatewayFault(GoogleGatewayFaultKind.TIMEOUT_BEFORE_DELIVERY),
    )

    try:
        gateway.update_task(
            task_list_id="task-list-default",
            task_id="task-followup",
            payload={"notes": "This should not land."},
        )
    except GoogleWorkspaceGatewayError as error:
        assert error.delivered is False
        assert error.mutated is False
    else:
        raise AssertionError("expected timeout-before-delivery fault")

    current = gateway.get_task(task_list_id="task-list-default", task_id="task-followup")
    assert current == original
