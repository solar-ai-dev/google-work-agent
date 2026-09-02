from installer.windows.uninstall_definition import WindowsUninstallDefinition


def test_default_uninstall__deletes_credentials_and__preserves_user_data() -> None:
    definition = WindowsUninstallDefinition()

    assert definition.delete_google_oauth_keyring_entry is True
    assert definition.delete_llm_api_key_keyring_entry is True
    assert definition.preserve_database_by_default is True
    assert definition.preserve_backups_by_default is True
    assert definition.preserve_settings_by_default is True
    assert definition.complete_delete_requires_explicit_confirmation is True
    assert {"data", "backups", "settings", "logs", "diagnostics"}.issubset(
        definition.complete_delete_paths
    )
