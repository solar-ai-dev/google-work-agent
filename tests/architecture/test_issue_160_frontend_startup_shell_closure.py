from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_issue_160_exact_frontend_owners_and_symbols_exist() -> None:
    expected = {
        "app/startup_flow.tsx": "export function StartupFlow",
        "features/diagnostics/startup_check.tsx": "export function StartupCheckScreen",
        "features/settings/first_run_onboarding.tsx": "export function FirstRunOnboardingScreen",
        "app/session_bootstrap.ts": "export async function bootstrapLocalSession",
        "app/api_compatibility_gate.tsx": "export function ApiCompatibilityGate",
        "app/main_shell.tsx": "export function MainShell",
        "app/top_bar.tsx": "export function TopBar",
    }
    for relative_path, symbol in expected.items():
        source = (FRONTEND / relative_path).read_text(encoding="utf-8")
        assert symbol in source, relative_path


def test_issue_160_app_uses_canonical_composition_without_legacy_owner() -> None:
    app_source = (FRONTEND / "app" / "App.tsx").read_text(encoding="utf-8")
    assert "<StartupFlow>" in app_source
    assert "<MainShell" in app_source
    assert "runStartup" not in app_source
    assert "readBootstrapFragment" not in app_source
    legacy_owner = FRONTEND / "features" / "onboarding"
    assert not list(legacy_owner.glob("*.ts*"))


def test_issue_160_bootstrap_secret_has_no_browser_storage_writer() -> None:
    session_source = (FRONTEND / "app" / "session_bootstrap.ts").read_text(encoding="utf-8")
    assert "localStorage" not in session_source
    assert "sessionStorage" not in session_source
    assert "indexedDB" not in session_source
    assert "bootstrapSession({ bootstrap_secret:" in session_source
    assert "clearFragment();" in session_source
