from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.application.projections import build_projection_event
from google_work_agent.ports import InvalidReplayCursorError, SnapshotRequiredReplayError


def test_in_memory_event_publisher_assigns_monotonic_ids_and_replays() -> None:
    publisher = InMemoryRunEventPublisher(service_instance_id="svc-a", capacity_per_run=4)
    first = publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=1,
            event_type="run_status",
            payload={"step": 1},
        )
    )
    second = publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=2,
            event_type="phase_changed",
            payload={"step": 2},
        )
    )

    assert first.event_id == "svc-a:1"
    assert second.event_id == "svc-a:2"
    assert publisher.replay(run_id="run-1", after_event_id="svc-a:1") == (second,)


def test_in_memory_event_publisher_requires_snapshot_after_eviction() -> None:
    publisher = InMemoryRunEventPublisher(service_instance_id="svc-a", capacity_per_run=2)
    publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=1,
            event_type="run_status",
            payload={"step": 1},
        )
    )
    publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=2,
            event_type="run_status",
            payload={"step": 2},
        )
    )
    publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=3,
            event_type="run_status",
            payload={"step": 3},
        )
    )
    publisher.publish(
        build_projection_event(
            run_id="run-1",
            occurred_at_ms=4,
            event_type="run_status",
            payload={"step": 4},
        )
    )

    try:
        publisher.replay(run_id="run-1", after_event_id="svc-a:1")
    except SnapshotRequiredReplayError:
        pass
    else:
        raise AssertionError("expected snapshot fallback after buffer eviction")

    try:
        publisher.replay(run_id="run-1", after_event_id="bad-cursor")
    except InvalidReplayCursorError:
        pass
    else:
        raise AssertionError("expected invalid cursor failure")
