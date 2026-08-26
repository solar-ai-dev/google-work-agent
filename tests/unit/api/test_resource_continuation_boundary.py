from dataclasses import replace
from typing import Any, cast

from tests.support.fakes import FakeClockPort

from google_work_agent.api.container import ApiContainer
from google_work_agent.application.resource_continuation import OpaqueResourceQueryService


def _container_with_resource_service(resource_query_service: object) -> ApiContainer:
    dynamic = cast(Any, None)
    return ApiContainer(
        unit_of_work_factory=lambda: dynamic,
        query_service=dynamic,
        create_conversation_handler=dynamic,
        start_run_service=dynamic,
        approve_action_service=dynamic,
        modify_action_service=dynamic,
        reject_action_service=dynamic,
        prepare_retry_service=dynamic,
        cancel_run_service=dynamic,
        resume_run_service=dynamic,
        local_run_coordinator=dynamic,
        workflow_runtime=dynamic,
        event_publisher=dynamic,
        readiness_aggregator=dynamic,
        runtime_status_provider=dynamic,
        api_access_guard=dynamic,
        clock=FakeClockPort(1),
        id_generator=dynamic,
        release_version="test",
        environment="test",
        service_instance_id="test-instance",
        resource_query_service=resource_query_service,
    )


def test_api_container_wraps_resource_query_service_once() -> None:
    raw_service = object()

    container = _container_with_resource_service(raw_service)

    assert isinstance(container.resource_query_service, OpaqueResourceQueryService)

    replaced = replace(container, environment="test-2")

    assert replaced.resource_query_service is container.resource_query_service
