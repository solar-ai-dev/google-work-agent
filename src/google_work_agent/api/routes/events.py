"""Run SSE routes."""

from __future__ import annotations

from collections.abc import Iterator
from json import dumps

from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse

from google_work_agent.api.dependencies import (
    EventRouteDependency,
    enforce_access,
    enforce_supported_api_contract_version,
)
from google_work_agent.api.errors import ApiError
from google_work_agent.application.projections import build_snapshot_required_event
from google_work_agent.ports import (
    EndpointPolicy,
    InvalidReplayCursorError,
    SnapshotRequiredReplayError,
)

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
    if dependencies.query_service().get_run_snapshot(run_id) is None:
        raise ApiError(
            error_code="NOT_FOUND",
            user_message="실행을 찾을 수 없습니다.",
            status_code=404,
            request_id=request.state.request_id,
        )

    def _stream() -> Iterator[str]:
        try:
            replayed = dependencies.event_publisher().replay(
                run_id=run_id, after_event_id=last_event_id
            )
            for event in replayed:
                yield _format_sse(event.event_id, event.event_type, event.payload)
        except (InvalidReplayCursorError, SnapshotRequiredReplayError) as error:
            fallback = build_snapshot_required_event(
                run_id=run_id,
                occurred_at_ms=dependencies.clock.now_ms(),
                reason=str(error),
            )
            published = dependencies.event_publisher().publish(fallback)
            yield _format_sse(published.event_id, published.event_type, published.payload)
            return

        subscription = dependencies.event_publisher().subscribe(run_id)
        try:
            while True:
                maybe_event = subscription.poll(0.1)
                if maybe_event is None:
                    yield ": keepalive\n\n"
                    continue
                yield _format_sse(
                    maybe_event.event_id,
                    maybe_event.event_type,
                    maybe_event.payload,
                )
        finally:
            dependencies.event_publisher().close_subscription(subscription)

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


def _format_sse(event_id: str, event_type: str, payload: dict[str, object]) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {dumps(payload, sort_keys=True)}\n\n"
