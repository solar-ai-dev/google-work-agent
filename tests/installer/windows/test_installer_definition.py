from pathlib import Path

from installer.windows.installer_definition import WindowsInstallerDefinition


def test_installer_is_per_user_x64_signed_and_rollback_capable(tmp_path: Path) -> None:
    definition = WindowsInstallerDefinition()

    assert definition.install_scope == "CURRENT_USER"
    assert definition.requires_administrator is False
    assert definition.require_code_signature is True
    assert definition.verify_release_signature_before_install is True
    assert definition.rollback_program_files_on_failure is True
    script = definition.render_inno_setup_script(
        bundle_root=tmp_path.resolve(),
        output_dir=(tmp_path / "out").resolve(),
        app_version="1.2.3",
        deployment_profile="API_ONLY",
    )
    assert "PrivilegesRequired=lowest" in script
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in script
    assert r"{localappdata}\Programs\GoogleWorkAgent" in script
    assert "GoogleWorkAgentCredentialCleanup.exe" in script
