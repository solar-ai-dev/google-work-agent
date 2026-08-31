from pathlib import Path

from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandContextV1,
)


def test_operational_replay_is_separate_from_domain_receipts_and_replays_result(
    tmp_path: Path,
) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path / "operations")
    context = OperationalCommandContextV1("cmd-1", "backup.create", "1" * 64)

    reserved = adapter.reserve_or_replay(context)
    adapter.store_result(context, "backup-1", {"size_bytes": 1})
    replayed = adapter.reserve_or_replay(context)

    assert reserved.decision == "PROCEED_NEW"
    assert replayed.decision == "REPLAY_COMPLETED"
    assert replayed.operation_ref == reserved.operation_ref
    assert replayed.bounded_result == {"size_bytes": 1}


def test_operational_replay_rejects_same_command_id_with_different_hash(tmp_path: Path) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path / "operations")
    adapter.reserve_or_replay(OperationalCommandContextV1("cmd-1", "backup.create", "1" * 64))

    conflict = adapter.reserve_or_replay(
        OperationalCommandContextV1("cmd-1", "backup.create", "2" * 64)
    )

    assert conflict.decision == "CONFLICT"


def test_operational_replay_recovers_reserved_and_uncertain_operations(tmp_path: Path) -> None:
    adapter = FilesystemOperationalCommandReplayAdapter(tmp_path / "operations")
    context = OperationalCommandContextV1("cmd-1", "backup.create", "1" * 64)

    adapter.reserve_or_replay(context)
    reserved = adapter.reserve_or_replay(context)
    adapter.mark_uncertain(context, "provider-recovery-1")
    uncertain = adapter.reserve_or_replay(context)

    assert reserved.decision == "RECOVER_RESERVED"
    assert reserved.reservation_status == "RESERVED"
    assert uncertain.decision == "RECOVER_RESERVED"
    assert uncertain.reservation_status == "UNCERTAIN"
    assert uncertain.recovery_ref == "provider-recovery-1"
