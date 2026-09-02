from installer.windows.upgrade_policy import WindowsUpgradePolicy


def test_upgrade_requires__signature_shutdown_backup__and_migration_readiness() -> None:
    policy = WindowsUpgradePolicy()
    assert (
        policy.assess(
            current_app_version="1.0.0",
            candidate_app_version="1.1.0",
            installer_signature_verified=True,
            application_stopped=True,
            active_write_safe=True,
            pre_migration_backup_created=True,
            migration_ready=True,
        ).allowed
        is True
    )
    assert (
        policy.assess(
            current_app_version="1.0.0",
            candidate_app_version="1.1.0",
            installer_signature_verified=False,
            application_stopped=True,
            active_write_safe=True,
            pre_migration_backup_created=True,
            migration_ready=True,
        ).reason_code
        == "INSTALLER_SIGNATURE_INVALID"
    )
    assert (
        policy.assess(
            current_app_version="1.0.0",
            candidate_app_version="1.1.0",
            installer_signature_verified=True,
            application_stopped=True,
            active_write_safe=True,
            pre_migration_backup_created=False,
            migration_ready=True,
        ).reason_code
        == "PRE_MIGRATION_BACKUP_REQUIRED"
    )


def test_downgrade_is__blocked_except__explicit_development_override() -> None:
    policy = WindowsUpgradePolicy()
    assert (
        policy.assess(
            current_app_version="2.0.0",
            candidate_app_version="1.0.0",
            installer_signature_verified=True,
            application_stopped=True,
            active_write_safe=True,
            pre_migration_backup_created=True,
            migration_ready=True,
        ).reason_code
        == "DOWNGRADE_BLOCKED"
    )
    assert (
        policy.assess(
            current_app_version="2.0.0",
            candidate_app_version="1.0.0",
            installer_signature_verified=True,
            application_stopped=True,
            active_write_safe=True,
            pre_migration_backup_created=True,
            migration_ready=True,
            development_downgrade_override=True,
        ).allowed
        is True
    )
