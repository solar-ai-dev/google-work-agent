"""Run SSE routes."""

from __future__ import annotations

from collections.abc import Iterator
from json import dumps

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from google_work_agent.api.dependencies.access_control import enforce_access
from google_work_agent.api.dependencies.contract_version import (
    enforce_supported_api_contract_version,
)
from google_work_agent.api.dependencies.events import EventRouteDependency
from google_work_agent.api.errors.api_request_error import ApiRequestError
from google_work_agent.application.use_cases.sse_event.list_run_events import (
    ListRunEventsHandler,
    ListRunEventsQuery,
)
from google_work_agent.ports.system.api_access_port import EndpointPolicy

router = APIRouter(prefix="/api/v1")


@router.get("/runs/{run_id}/events")
def stream_events(
    run_id: str,
    request: Request,
    dependencies: EventRouteDependency,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    x_api_contract_version: str | None = Header(default=None),
) -> StreamingResponse:
    enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
    enforce_supported_api_contract_version(
        supported_version=dependencies.api_contract_version,
        request_id=request.state.request_id,
        request_version=x_api_contract_version,
    )
    replay = ListRunEventsHandler(
        unit_of_work_factory=dependencies.unit_of_work_factory,
        event_buffer=dependencies.event_publisher(),
    )(ListRunEventsQuery(run_id=run_id, last_event_id=last_event_id))
    if not replay.run_exists:
        raise ApiRequestError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )
    publisher = dependencies.event_publisher()

    def _stream() -> Iterator[str]:
        for event in replay.events:
            yield _format_sse(event.event_id, event.event_type, event.payload)
        if replay.cursor_status == "CURSOR_EXPIRED":
            yield _format_sse("", "snapshot_required", {"run_id": run_id})
            return
        subscription = publisher.subscribe(run_id)
        try:
            while True:
                maybe_event = subscription.poll(0.1)
                if maybe_event is None:
                    yield ": keepalive\n\n"
                    continue
                yield _format_sse(maybe_event.event_id, maybe_event.event_type, maybe_event.payload)
        finally:
            publisher.close_subscription(subscription)

    return StreamingResponse(
        _stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )


def _format_sse(event_id: str, event_type: str, payload: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {dumps(payload, sort_keys=True)}\n\n"
