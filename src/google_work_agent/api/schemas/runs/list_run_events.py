"""Serialize the canonical Run-scoped SSE wire envelope without redefining it."""

from google_work_agent.ports.system.sse_event_buffer_port import RunSseEventV1


def serialize_run_sse_event(event: RunSseEventV1) -> dict[str, object]:
    return event.model_dump(mode="json")


__all__ = ["serialize_run_sse_event"]
