from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_issue_163_exact_frontend_owners_exist() -> None:
    expected = {
        "features/settings/settings_drawer.tsx": "SettingsDrawer",
        "features/diagnostics/diagnostics_panel.tsx": "DiagnosticsPanel",
        "features/attachment/attachment_list.tsx": "AttachmentList",
        "features/attachment/api/download_attachment.ts": "downloadAttachment",
        "features/attachment/attachment_picker.tsx": "AttachmentPicker",
        "features/attachment/api/stage_attachment.ts": "stageAttachment",
    }
    for relative, symbol in expected.items():
        source = (FRONTEND / relative).read_text(encoding="utf-8")
        assert symbol in source


def test_issue_163_has_no_broad_or_legacy_frontend_authority() -> None:
    assert not (FRONTEND / "features/settings/SettingsDrawer.tsx").exists()
    root_api = (FRONTEND / "api/index.ts").read_text(encoding="utf-8")
    for forbidden in (
        "getRuntime",
        "getSettings",
        "stageAttachment",
        "storeLLMApiKey",
        "startGoogleOAuth",
    ):
        assert forbidden not in root_api
    action_plan = (FRONTEND / "features/approval/action_plan_card.tsx").read_text(encoding="utf-8")
    action_commands = (FRONTEND / "features/approval/use_action_plan_commands.ts").read_text(
        encoding="utf-8"
    )
    assert 'type="file"' not in action_plan
    assert "slice(0, 10)" not in action_commands
    assert "stageAttachment" not in action_commands
    resource_viewer = (FRONTEND / "features/resource_browser/resource_viewer.tsx").read_text(
        encoding="utf-8"
    )
    assert "requestBlob" not in resource_viewer
    assert "URL.createObjectURL" not in resource_viewer


def test_issue_163_operational_identity_and_secret_negative_proof() -> None:
    settings = (FRONTEND / "features/settings/settings_drawer.tsx").read_text(encoding="utf-8")
    onboarding = (FRONTEND / "features/settings/first_run_onboarding.tsx").read_text(
        encoding="utf-8"
    )
    assert "Date.now()" not in settings
    assert "Date.now()" not in onboarding
    assert 'setApiKey("")' in settings
    assert 'setApiKey("")' in onboarding
    assert "localStorage" not in settings
