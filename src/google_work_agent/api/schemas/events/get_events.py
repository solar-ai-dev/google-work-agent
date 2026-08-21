"""Get-run-events SSE envelope."""

from google_work_agent.api.schemas.common import ApiModel


class EventEnvelope(ApiModel):
    event_id: str
    run_id: str
    occurred_at_ms: int
    event_type: str
    payload: dict[str, object]
    projection_version: int
    schema_version: int
    action_id: str | None = None
