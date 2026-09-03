"""Project one canonical Run fact into the process-local SSE buffer."""

from dataclasses import dataclass

from google_work_agent.ports.system.sse_event_buffer_port import (
    RunSseEventTypeV1,
    RunSseEventV1,
    SseEventBufferPort,
)


@dataclass(frozen=True, slots=True)
class ProjectRunEventCommand:
    run_id: str
    occurred_at_ms: int
    event_type: RunSseEventTypeV1
    payload: dict[str, object]
    action_id: str | None = None
    projection_version: int = 1


class ProjectRunEventHandler:
    def __init__(self, event_buffer: SseEventBufferPort) -> None:
        self._event_buffer = event_buffer

    def __call__(self, command: ProjectRunEventCommand) -> RunSseEventV1:
        event = RunSseEventV1.model_validate(
            {
                "schema_version": 1,
                "event_id": "pending",
                "run_id": command.run_id,
                "action_id": command.action_id,
                "occurred_at_ms": command.occurred_at_ms,
                "event_type": command.event_type,
                "payload": command.payload,
                "projection_version": command.projection_version,
            }
        )
        self._event_buffer.append(event)
        return event


__all__ = ["ProjectRunEventCommand", "ProjectRunEventHandler", "RunSseEventV1"]
