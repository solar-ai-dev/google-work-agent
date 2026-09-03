from google_work_agent.application.use_cases.setting.get_settings import GetSettingsHandler


def test_get_settings__has_exact__application_owner() -> None:
    assert (
        GetSettingsHandler.__module__
        == "google_work_agent.application.use_cases.setting.get_settings"
    )
    assert GetSettingsHandler.__name__ == "GetSettingsHandler"
