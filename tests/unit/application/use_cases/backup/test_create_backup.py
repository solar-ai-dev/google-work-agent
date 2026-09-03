from google_work_agent.application.use_cases.backup.create_backup import CreateBackupHandler


def test_create_backup__has_exact__application_owner() -> None:
    assert (
        CreateBackupHandler.__module__
        == "google_work_agent.application.use_cases.backup.create_backup"
    )
    assert CreateBackupHandler.__name__ == "CreateBackupHandler"
