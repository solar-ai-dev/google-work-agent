from google_work_agent.application.use_cases.backup.list_backups import ListBackupsHandler


def test_list_backups__has_exact__application_owner() -> None:
    assert (
        ListBackupsHandler.__module__
        == "google_work_agent.application.use_cases.backup.list_backups"
    )
    assert ListBackupsHandler.__name__ == "ListBackupsHandler"
