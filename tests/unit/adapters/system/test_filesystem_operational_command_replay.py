from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandContextV1,
)


def test_operational_replay_is_separate_from_domain_receipts_and_replays_result(tmp_path) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path / "operations")
    context = OperationalCommandContextV1("cmd-1", "backup.create", "hash-1")

    reserved = adapter.reserve_or_replay(context)
    adapter.store_result(context, "backup-1", {"size_bytes": 1})
    replayed = adapter.reserve_or_replay(context)

    assert reserved.kind == "RESERVED"
    assert replayed.kind == "COMPLETED"
    assert replayed.operation_ref == reserved.operation_ref
    assert replayed.bounded_result == {"size_bytes": 1}


def test_operational_replay_rejects_same_command_id_with_different_hash(tmp_path) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path / "operations")
    adapter.reserve_or_replay(OperationalCommandContextV1("cmd-1", "backup.create", "hash-1"))

    conflict = adapter.reserve_or_replay(
        OperationalCommandContextV1("cmd-1", "backup.create", "hash-2")
    )

    assert conflict.kind == "CONFLICT"
