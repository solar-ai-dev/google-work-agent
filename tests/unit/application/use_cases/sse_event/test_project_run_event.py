from collections.abc import Mapping
from typing import cast

import pytest
from pydantic import ValidationError

from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.ports.system.sse_event_buffer_port import (
    RUN_SSE_EVENT_TYPES_V1,
    SSE_PAYLOAD_TYPE_BY_EVENT_V1,
    RunSseEventTypeV1,
    RunSseEventV1,
    SseEventPageV1,
    SsePayloadV1,
)

VALID_PAYLOADS: Mapping[str, dict[str, object]] = {
    "run_status": {"status": "ANALYZING", "snapshot_version": 2},
    "phase_changed": {"phase": "TOOL_ROUTING"},
    "tool_routing": {"route_revision": 3, "input_route_count": 2, "output_mode": "ACTION"},
    "retrieval_progress": {"coverage": "PARTIAL", "completed_sources": 1, "total_sources": 2},
    "confirmation_required": {
        "interrupt_id": "i-1",
        "question": "계속할까요?",
        "options": ["예", "아니요"],
    },
    "analysis_progress": {"completed_stage": "WORK_ANALYSIS"},
    "plan_updated": {"plan_id": "p-1", "revision_no": 4},
    "approval_required": {"action_ids": ["a-1"]},
    "action_status": {"action_id": "a-1", "status": "APPROVED"},
    "verification_result": {"action_id": "a-1", "outcome": "VERIFIED"},
    "reauth_required": {"connector_id": "google"},
    "recovery_required": {
        "recovery": {
            "reason_code": "CHECKPOINT_MISMATCH",
            "message": "안전한 지점부터 다시 확인할 수 있습니다.",
            "target": {"target_kind": "RUN"},
            "allowed_resolution_kinds": ["RECHECK", "CANCEL", "FAIL"],
        }
    },
    "completed": {"status": "COMPLETED", "result_kind": "SUCCESS"},
    "error": {"error_code": "INTERNAL_ERROR", "recoverable": False},
}


class _Buffer:
    def __init__(self) -> None:
        self.events: list[RunSseEventV1] = []

    def append(self, event: RunSseEventV1) -> None:
        self.events.append(event)

    def list_after(self, run_id: str, last_event_id: str | None, limit: int) -> SseEventPageV1:
        raise NotImplementedError

    def clear_run(self, run_id: str) -> None:
        raise NotImplementedError


def _command(event_type: str, payload: dict[str, object]) -> ProjectRunEventCommand:
    return ProjectRunEventCommand(
        run_id="run-1",
        occurred_at_ms=10,
        event_type=cast(RunSseEventTypeV1, event_type),
        payload=payload,
    )


@pytest.mark.parametrize(("event_type", "payload"), VALID_PAYLOADS.items())
def test_canonical_event__projects_once__through_handler(
    event_type: str, payload: dict[str, object]
) -> None:
    buffer = _Buffer()
    event = ProjectRunEventHandler(buffer)(_command(event_type, payload))
    assert event.event_type == event_type
    assert type(event.payload) is SSE_PAYLOAD_TYPE_BY_EVENT_V1[event_type]
    assert buffer.events == [event]


def test_contract__has_exact_event__and_envelope_sets() -> None:
    assert set(SSE_PAYLOAD_TYPE_BY_EVENT_V1) == RUN_SSE_EVENT_TYPES_V1
    assert set(VALID_PAYLOADS) == RUN_SSE_EVENT_TYPES_V1
    assert set(RunSseEventV1.model_fields) == {
        "schema_version",
        "event_id",
        "run_id",
        "action_id",
        "occurred_at_ms",
        "event_type",
        "payload",
        "projection_version",
    }


@pytest.mark.parametrize(
    ("event_type", "payload_type"),
    list(zip(VALID_PAYLOADS, [*list(VALID_PAYLOADS)[1:], next(iter(VALID_PAYLOADS))], strict=True)),
)
def test_event_type__rejects_mismatched__payload_model(event_type: str, payload_type: str) -> None:
    buffer = _Buffer()
    with pytest.raises(ValidationError):
        ProjectRunEventHandler(buffer)(_command(event_type, VALID_PAYLOADS[payload_type]))
    assert buffer.events == []


@pytest.mark.parametrize("event_type", ["UNKNOWN", "RUN_UPDATED", "EXTERNAL_LLM_SCOPE_PUBLISHED"])
def test_unknown_non_sse__event_types_fail__before_append(event_type: str) -> None:
    buffer = _Buffer()
    with pytest.raises(ValidationError):
        ProjectRunEventHandler(buffer)(_command(event_type, VALID_PAYLOADS["run_status"]))
    assert buffer.events == []


@pytest.mark.parametrize(
    "value",
    [
        ("run_status", {"status": "CREATED"}),
        ("run_status", {"status": "CREATED", "snapshot_version": 1, "prompt": "raw"}),
        ("phase_changed", {"status": "CREATED", "snapshot_version": 1}),
    ],
)
def test_malformed_raw__authority_fields_fail__closed(
    value: tuple[str, dict[str, object]],
) -> None:
    buffer = _Buffer()
    with pytest.raises(ValidationError):
        ProjectRunEventHandler(buffer)(_command(*value))
    assert buffer.events == []


@pytest.mark.parametrize(("field", "value"), [("checkpoint_blob", {}), ("schema_version", 2)])
def test_envelope__rejects_undeclared__fields(field: str, value: object) -> None:
    event = {
        "schema_version": 1,
        "event_id": "1",
        "run_id": "run-1",
        "action_id": None,
        "occurred_at_ms": 1,
        "event_type": "run_status",
        "payload": VALID_PAYLOADS["run_status"],
        "projection_version": 1,
    }
    event[field] = value
    with pytest.raises(ValidationError):
        RunSseEventV1.model_validate(event)


def test_payload_union__has_no_arbitrary__dict_fallback() -> None:
    assert dict not in getattr(SsePayloadV1, "__args__", ())
