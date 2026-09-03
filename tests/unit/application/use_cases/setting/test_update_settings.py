from google_work_agent.application.use_cases.setting.update_settings import UpdateSettingsHandler


def test_update_settings__has_exact__application_owner() -> None:
    assert (
        UpdateSettingsHandler.__module__
        == "google_work_agent.application.use_cases.setting.update_settings"
    )
    assert UpdateSettingsHandler.__name__ == "UpdateSettingsHandler"
