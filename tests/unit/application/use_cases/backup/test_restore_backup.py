from google_work_agent.application.use_cases.backup.restore_backup import RestoreBackupHandler


def test_restore_backup__has_exact__application_owner() -> None:
    assert (
        RestoreBackupHandler.__module__
        == "google_work_agent.application.use_cases.backup.restore_backup"
    )
    assert RestoreBackupHandler.__name__ == "RestoreBackupHandler"
