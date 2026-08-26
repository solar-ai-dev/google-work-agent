"""Settings storage boundary."""

from typing import Protocol

from google_work_agent.ports.runtime_contracts import AppSettings, SettingsPatch


class SettingsPort(Protocol):
    def get(self) -> AppSettings: ...
    def patch(self, patch: SettingsPatch) -> AppSettings: ...
