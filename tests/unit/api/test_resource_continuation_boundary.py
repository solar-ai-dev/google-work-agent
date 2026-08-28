from dataclasses import replace
from typing import Any, cast

from tests.support.fakes import FakeClockPort

from google_work_agent.api.container import ApiContainer
from google_work_agent.application.use_cases.resource.opaque_continuation_access import (
    OpaqueConnectorResourceAccess,
)


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
    wrapped_service = OpaqueConnectorResourceAccess(cast(Any, raw_service))

    container = _container_with_resource_service(wrapped_service)

    assert container.resource_query_service is wrapped_service

    replaced = replace(container, environment="test-2")

    assert replaced.resource_query_service is container.resource_query_service
