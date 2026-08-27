from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalCommandContextV1,
)


def test_operational_command_replay_is_deterministic_and_conflict_safe(tmp_path) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path)
    context = OperationalCommandContextV1("command-1", "SETTINGS_UPDATE", "a" * 64)

    reserved = adapter.reserve_or_replay(context)
    recovered = adapter.reserve_or_replay(context)
    adapter.store_result(context, "result-1", {"status": "ok"})
    replayed = adapter.reserve_or_replay(context)
    conflict = adapter.reserve_or_replay(
        OperationalCommandContextV1("command-1", "SETTINGS_UPDATE", "b" * 64)
    )

    assert reserved.decision == "PROCEED_NEW"
    assert recovered.decision == "RECOVER_RESERVED"
    assert recovered.operation_ref == reserved.operation_ref
    assert replayed.decision == "REPLAY_COMPLETED"
    assert replayed.bounded_result == {"status": "ok"}
    assert conflict.decision == "CONFLICT"
