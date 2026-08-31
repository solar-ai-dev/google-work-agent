from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_issue_161_exact_owners_and_symbols_exist() -> None:
    expected = {
        "features/resource_browser/resource_sidebar.tsx": "export function ResourceSidebar",
        "features/resource_browser/resource_viewer.tsx": "export function ResourceViewer",
        "features/resource_browser/api/list_resources.ts": "export function listResources",
        "features/resource_browser/session_page_cache.ts": (
            "export class ResourceBrowserSessionCache"
        ),
        "features/resource_browser/selected_resource_context.ts": (
            "export function buildSelectedResourceContext"
        ),
        "features/run/request_composer.tsx": "export function RequestComposer",
        "features/conversation/conversation_history_panel.tsx": (
            "export function ConversationHistoryPanel"
        ),
        "features/conversation/api/get_conversation_history.ts": (
            "export function getConversationHistory"
        ),
    }
    for relative_path, symbol in expected.items():
        source = (FRONTEND / relative_path).read_text(encoding="utf-8")
        assert symbol in source, relative_path


def test_issue_161_app_and_controller_use_canonical_owners_only() -> None:
    app = (FRONTEND / "app" / "App.tsx").read_text(encoding="utf-8")
    conversation = (FRONTEND / "features" / "conversation" / "useConversation.ts").read_text(
        encoding="utf-8"
    )
    api_index = (FRONTEND / "api" / "index.ts").read_text(encoding="utf-8")
    assert "<ResourceSidebar" in app
    assert "<ResourceViewer" in app
    assert "resourceState" not in app
    assert "setResourceState" not in app
    assert "useConversationHistoryProjection" in conversation
    assert "useRequestComposerController" in conversation
    for legacy_symbol in (
        "listConversations",
        "createConversation",
        "getConversationHistory",
        "startRun",
        "listGmailResources",
        "getGmailResourceDetail",
        "downloadGmailAttachment",
        "listTaskResources",
        "listCalendarResources",
        "getResourceCount",
    ):
        assert f"export function {legacy_symbol}" not in api_index
    assert not (FRONTEND / "features" / "conversation" / "ConversationSidebar.tsx").exists()


def test_issue_161_browser_trust_and_storage_negative_proof() -> None:
    scoped = [
        FRONTEND / "features" / "resource_browser",
        FRONTEND / "features" / "conversation",
        FRONTEND / "features" / "run" / "request_composer.tsx",
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for owner in scoped
        for path in ([owner] if owner.is_file() else owner.rglob("*.ts*"))
    )
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "indexedDB" not in source
    assert "@google" not in source
    assert "googleapiclient" not in source
    assert "selected_resource_handles: selectionHandles" in source
    assert "history:" not in (FRONTEND / "features" / "run" / "request_composer.tsx").read_text(
        encoding="utf-8"
    )
