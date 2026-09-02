from dataclasses import replace
from typing import Any, cast

from tests.support.fakes import FakeClockPort

from google_work_agent.api.container import ApiContainer


def _container_with_list_handler(handler: object) -> ApiContainer:
    dynamic = cast(Any, None)
    return ApiContainer(
        unit_of_work_factory=lambda: dynamic,
        create_conversation_handler=dynamic,
        start_run_service=dynamic,
        approve_action_service=dynamic,
        modify_action_service=dynamic,
        reject_action_service=dynamic,
        prepare_retry_service=dynamic,
        cancel_run_service=dynamic,
        resume_run_service=dynamic,
        workflow_runtime=dynamic,
        event_publisher=dynamic,
        readiness_aggregator=dynamic,
        api_access_guard=dynamic,
        clock=FakeClockPort(1),
        id_generator=dynamic,
        release_version="test",
        environment="test",
        service_instance_id="test-instance",
        list_resources_handler=handler,
    )


def test_api_container__preserves_exact__resource_handler_binding() -> None:
    handler = object()
    container = _container_with_list_handler(handler)

    assert container.list_resources_handler is handler

    replaced = replace(container, environment="test-2")

    assert replaced.list_resources_handler is container.list_resources_handler
