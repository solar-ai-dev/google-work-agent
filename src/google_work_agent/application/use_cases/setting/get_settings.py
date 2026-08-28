"""Read the canonical typed settings view."""

from dataclasses import dataclass

from google_work_agent.ports.system.settings_port import SettingsPort, SettingsViewV1


@dataclass(frozen=True, slots=True)
class GetSettingsQuery:
    pass


@dataclass(frozen=True, slots=True)
class GetSettingsResult:
    settings: SettingsViewV1


class GetSettingsHandler:
    def __init__(self, settings: SettingsPort) -> None:
        self._settings = settings

    def __call__(self, query: GetSettingsQuery) -> GetSettingsResult:
        del query
        return GetSettingsResult(self._settings.get_settings())


__all__ = ["GetSettingsHandler", "GetSettingsQuery", "GetSettingsResult"]
