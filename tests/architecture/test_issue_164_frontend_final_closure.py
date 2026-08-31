from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SOURCE = FRONTEND / "src"

FORMAL_OWNERS = {
    "STR-011": ("app/startup_flow.tsx", "StartupFlow", "tests/app/startup_flow.test.tsx"),
    "STR-012": (
        "features/diagnostics/startup_check.tsx",
        "StartupCheckScreen",
        "tests/features/diagnostics/startup_check.test.tsx",
    ),
    "STR-013": (
        "features/settings/first_run_onboarding.tsx",
        "FirstRunOnboardingScreen",
        "tests/features/settings/first_run_onboarding.test.tsx",
    ),
    "STR-014": (
        "app/session_bootstrap.ts",
        "bootstrapLocalSession",
        "tests/app/session_bootstrap.test.ts",
    ),
    "STR-015": (
        "app/api_compatibility_gate.tsx",
        "ApiCompatibilityGate",
        "tests/app/api_compatibility_gate.test.tsx",
    ),
    "STR-016": ("app/main_shell.tsx", "MainShell", "tests/app/main_shell.test.tsx"),
    "STR-017": ("app/top_bar.tsx", "TopBar", "tests/app/top_bar.test.tsx"),
    "STR-018": (
        "features/resource_browser/resource_sidebar.tsx",
        "ResourceSidebar",
        "tests/features/resource_browser/resource_sidebar.test.tsx",
    ),
    "STR-019": (
        "features/resource_browser/resource_viewer.tsx",
        "ResourceViewer",
        "tests/features/resource_browser/resource_viewer.test.tsx",
    ),
    "STR-020": (
        "features/resource_browser/api/list_resources.ts",
        "listResources",
        "tests/features/resource_browser/api/list_resources.test.ts",
    ),
    "STR-021": (
        "features/resource_browser/session_page_cache.ts",
        "ResourceBrowserSessionCache",
        "tests/features/resource_browser/session_page_cache.test.ts",
    ),
    "STR-022": (
        "features/resource_browser/selected_resource_context.ts",
        "buildSelectedResourceContext",
        "tests/features/resource_browser/selected_resource_context.test.ts",
    ),
    "STR-023": (
        "features/run/request_composer.tsx",
        "RequestComposer",
        "tests/features/run/request_composer.test.tsx",
    ),
    "STR-024": (
        "features/run/api/subscribe_run_events.ts",
        "subscribeRunEvents",
        "tests/features/run/api/subscribe_run_events.test.ts",
    ),
    "STR-025": (
        "features/run/run_progress.tsx",
        "RunProgress",
        "tests/features/run/run_progress.test.tsx",
    ),
    "STR-026": (
        "features/run/confirmation_card.tsx",
        "ConfirmationCard",
        "tests/features/run/confirmation_card.test.tsx",
    ),
    "STR-027": (
        "features/run/execution_status_card.tsx",
        "ExecutionStatusCard",
        "tests/features/run/execution_status_card.test.tsx",
    ),
    "STR-028": (
        "features/conversation/conversation_history_panel.tsx",
        "ConversationHistoryPanel",
        "tests/features/conversation/conversation_history_panel.test.tsx",
    ),
    "STR-029": (
        "features/conversation/api/get_conversation_history.ts",
        "getConversationHistory",
        "tests/features/conversation/api/get_conversation_history.test.ts",
    ),
    "STR-030": (
        "features/approval/action_plan_card.tsx",
        "ActionPlanCard",
        "tests/features/approval/action_plan_card.test.tsx",
    ),
    "STR-031": (
        "features/recovery/recovery_card.tsx",
        "RecoveryCard",
        "tests/features/recovery/recovery_card.test.tsx",
    ),
    "STR-032": (
        "features/settings/settings_drawer.tsx",
        "SettingsDrawer",
        "tests/features/settings/settings_drawer.test.tsx",
    ),
    "STR-033": (
        "features/diagnostics/diagnostics_panel.tsx",
        "DiagnosticsPanel",
        "tests/features/diagnostics/diagnostics_panel.test.tsx",
    ),
    "STR-034": (
        "features/attachment/attachment_list.tsx",
        "AttachmentList",
        "tests/features/attachment/attachment_list.test.tsx",
    ),
    "STR-035": (
        "features/attachment/api/download_attachment.ts",
        "downloadAttachment",
        "tests/features/attachment/api/download_attachment.test.ts",
    ),
    "STR-036": (
        "features/attachment/attachment_picker.tsx",
        "AttachmentPicker",
        "tests/features/attachment/attachment_picker.test.tsx",
    ),
    "STR-037": (
        "features/attachment/api/stage_attachment.ts",
        "stageAttachment",
        "tests/features/attachment/api/stage_attachment.test.ts",
    ),
}


def _production_sources() -> list[Path]:
    return sorted(
        path
        for path in SOURCE.rglob("*.ts*")
        if not path.name.endswith(".test.ts") and not path.name.endswith(".test.tsx")
    )


def test_issue_164_accounts_for_all_28_formal_frontend_rows() -> None:
    assert (FRONTEND / "package.json").is_file()  # STR-007 repository root
    assert len(FORMAL_OWNERS) == 27
    for row_id, (source_path, symbol, test_path) in FORMAL_OWNERS.items():
        source = (SOURCE / source_path).read_text(encoding="utf-8")
        assert symbol in source, row_id
        assert (FRONTEND / test_path).is_file(), row_id


def test_issue_164_has_one_root_and_no_retired_wrong_owner_modules() -> None:
    main = (SOURCE / "main.tsx").read_text(encoding="utf-8")
    app = (SOURCE / "app/App.tsx").read_text(encoding="utf-8")
    assert main.count("<App") == 1
    assert "export function App" in app
    for retired in (
        "app/CalendarMonthView.tsx",
        "app/CalendarMonthView.test.tsx",
        "features/workspace/CenterWorkspace.tsx",
        "features/workspace/ResourceDetail.tsx",
        "features/workspace/index.ts",
        "features/gmail/useGmail.ts",
        "features/tasks/useTasks.ts",
        "features/calendar/useCalendar.ts",
    ):
        assert not (SOURCE / retired).exists(), retired


def test_issue_164_app_and_peer_features_use_only_public_feature_apis() -> None:
    app_import = re.compile(r'from\s+["\']\.\./features/([^"\']+)["\']')
    for path in (SOURCE / "app").glob("*.ts*"):
        if ".test." in path.name:
            continue
        for target in app_import.findall(path.read_text(encoding="utf-8")):
            assert "/" not in target, f"private feature import: {path}: {target}"

    feature_import = re.compile(r'from\s+["\']\.\./([a-z_]+)(/[^"\']+)?["\']')
    graph: dict[str, set[str]] = {}
    for owner_dir in (SOURCE / "features").iterdir():
        if not owner_dir.is_dir():
            continue
        graph[owner_dir.name] = set()
        for path in owner_dir.rglob("*.ts*"):
            for target_owner, private_suffix in feature_import.findall(
                path.read_text(encoding="utf-8")
            ):
                if target_owner == owner_dir.name:
                    continue
                assert not private_suffix, (
                    f"private peer import: {path}: {target_owner}{private_suffix}"
                )
                graph[owner_dir.name].add(target_owner)

    def visit(owner: str, stack: tuple[str, ...]) -> None:
        assert owner not in stack, "feature ownership cycle: " + " -> ".join((*stack, owner))
        for dependency in graph.get(owner, set()):
            visit(dependency, (*stack, owner))

    for owner in graph:
        visit(owner, ())


def test_issue_164_network_and_browser_storage_stay_inside_reviewed_boundaries() -> None:
    sources = {
        path.relative_to(SOURCE).as_posix(): path.read_text(encoding="utf-8")
        for path in _production_sources()
    }
    fetch_owners = {name for name, source in sources.items() if re.search(r"\bfetch\s*\(", source)}
    event_source_owners = {name for name, source in sources.items() if "new EventSource(" in source}
    storage_owners = {name for name, source in sources.items() if "localStorage" in source}
    assert fetch_owners == {"api/client.ts"}
    assert event_source_owners == {"features/run/api/subscribe_run_events.ts"}
    assert storage_owners == {"app/App.tsx", "app/main_shell.tsx"}
    transport_callers = {
        name
        for name, source in sources.items()
        if "requestJson" in source or "requestBlobResponse" in source
    }
    assert all(
        name in {"api/client.ts", "api/index.ts"} or "/api/" in name for name in transport_callers
    ), transport_callers
    combined = "\n".join(sources.values())
    for forbidden in (
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "navigator.serviceWorker",
        "window.caches",
        "@googleapis",
        "googleapis",
        "sqlite3",
        "child_process",
    ):
        assert forbidden not in combined
    assert "gwa.settings" not in combined


def test_issue_164_current_api_identity_and_approval_contracts_are_enforced() -> None:
    contract = (SOURCE / "api/contract.ts").read_text(encoding="utf-8")
    resource_api = (SOURCE / "features/resource_browser/api/list_resources.ts").read_text(
        encoding="utf-8"
    )
    composer = (SOURCE / "features/run/request_composer.tsx").read_text(encoding="utf-8")
    approval = (SOURCE / "features/approval/action_plan_card.tsx").read_text(encoding="utf-8")
    for exact_field in (
        "exact_count",
        "projection_version",
        "selection_handle",
        "has_attachments",
        "task_status",
        "calendar_id",
    ):
        assert exact_field in contract
    assert "response.exact_count" in (
        SOURCE / "features/resource_browser/gmail_controller.ts"
    ).read_text(encoding="utf-8")
    assert "payload.total_count" not in resource_api
    assert "metadata: Record<string, unknown>" not in contract
    assert "conversationCommandId" in composer
    assert "runCommandId" in composer
    assert "crypto.randomUUID" not in composer
    assert "missingAcknowledgement" in approval
    assert "onApprove(action, acknowledgements)" in approval
    assert "new Set(requiredAcknowledgements)" not in approval
