"""Update non-secret settings through crash-safe operational replay."""

from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.operational_replay import execute_operational_command
from google_work_agent.ports.system.operational_command_replay_port import (
    OperationalCommandReplayPort,
)
from google_work_agent.ports.system.settings_port import (
    PanelPreferencesV1,
    SettingsPatchV1,
    SettingsPort,
    SettingsViewV1,
)


@dataclass(frozen=True, slots=True)
class UpdateSettingsCommand:
    command_id: str
    settings_patch: SettingsPatchV1


@dataclass(frozen=True, slots=True)
class UpdateSettingsResult:
    settings: SettingsViewV1
    operation_ref: str
    replayed: bool


class UpdateSettingsHandler:
    def __init__(self, *, settings: SettingsPort, replay: OperationalCommandReplayPort) -> None:
        self._settings = settings
        self._replay = replay

    def __call__(self, command: UpdateSettingsCommand) -> UpdateSettingsResult:
        def execute(ref: str) -> tuple[str, dict[str, object]]:
            value = self._settings.update_settings(command.settings_patch, ref)
            return ref, asdict(value)

        outcome = execute_operational_command(
            replay_port=self._replay,
            command_id=command.command_id,
            operation_kind="UPDATE_SETTINGS",
            request_payload=cast(dict[str, object], asdict(command.settings_patch)),
            reconcile=lambda ref: self._settings.reconcile_settings(ref, command.settings_patch),
            execute=execute,
        )
        payload = cast(dict[str, object], outcome.bounded_result)
        payload["panel_preferences"] = PanelPreferencesV1(**cast(Any, payload["panel_preferences"]))
        return UpdateSettingsResult(
            settings=SettingsViewV1(**cast(Any, payload)),
            operation_ref=outcome.operation_ref,
            replayed=outcome.replayed,
        )


__all__ = ["UpdateSettingsCommand", "UpdateSettingsHandler", "UpdateSettingsResult"]
