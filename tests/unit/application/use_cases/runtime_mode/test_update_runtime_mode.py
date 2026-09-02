from pathlib import Path

from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.process_runtime_mode import ProcessRuntimeModeAdapter
from google_work_agent.application.use_cases.runtime_mode.update_runtime_mode import (
    UpdateRuntimeModeCommand,
    UpdateRuntimeModeHandler,
)


def test_runtime_mode__update_is__replay_safe(tmp_path: Path) -> None:
    handler = UpdateRuntimeModeHandler(
        runtime_mode=ProcessRuntimeModeAdapter("AUTO"),
        replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        has_active_run=lambda: False,
    )

    first = handler(UpdateRuntimeModeCommand("command-1", "API_LLM"))
    replay = handler(UpdateRuntimeModeCommand("command-1", "API_LLM"))

    assert first.requested_mode == "API_LLM"
    assert first.replayed is False
    assert replay.requested_mode == "API_LLM"
    assert replay.replayed is True


def test_runtime_mode_update_is__blocked_before_reservation_when__a_run_is_active(
    tmp_path: Path,
) -> None:
    replay = FilesystemOperationalCommandReplayAdapter(tmp_path / "replay")
    handler = UpdateRuntimeModeHandler(
        runtime_mode=ProcessRuntimeModeAdapter("AUTO"),
        replay=replay,
        has_active_run=lambda: True,
    )

    try:
        handler(UpdateRuntimeModeCommand("command-1", "API_LLM"))
    except RuntimeError as error:
        assert str(error) == "RUNTIME_MODE_CHANGE_BLOCKED_BY_ACTIVE_RUN"
    else:
        raise AssertionError("active Run must block a runtime-mode mutation")

    assert list((tmp_path / "replay").glob("*.json")) == []
