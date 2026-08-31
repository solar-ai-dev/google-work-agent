from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_issue_162_exact_owners_and_symbols_exist() -> None:
    expected = {
        "features/run/api/subscribe_run_events.ts": "export function subscribeRunEvents",
        "features/run/run_progress.tsx": "export function RunProgress",
        "features/run/confirmation_card.tsx": "export function ConfirmationCard",
        "features/run/execution_status_card.tsx": "export function ExecutionStatusCard",
        "features/approval/action_plan_card.tsx": "export function ActionPlanCard",
        "features/recovery/recovery_card.tsx": "export function RecoveryCard",
    }
    for relative_path, symbol in expected.items():
        assert symbol in (FRONTEND / relative_path).read_text(encoding="utf-8")


def test_issue_162_conversation_view_composes_exact_feature_owners() -> None:
    source = (FRONTEND / "features" / "conversation" / "ConversationView.tsx").read_text(
        encoding="utf-8"
    )
    for symbol in (
        "<RunProgress",
        "<ConfirmationCard",
        "<ExecutionStatusCard",
        "<ActionPlanCard",
        "<RecoveryCard",
    ):
        assert symbol in source
    for duplicate_authority in (
        "window.prompt",
        "WAITING_APPROVAL",
        "UNKNOWN_RESULT",
        "MISMATCH",
        "calendarConflictDecision",
        "taskDuplicateDecision",
    ):
        assert duplicate_authority not in source


def test_issue_162_legacy_and_duplicate_authority_negative_proof() -> None:
    assert not (FRONTEND / "api" / "sse.ts").exists()
    controller = (FRONTEND / "features" / "conversation" / "useConversation.ts").read_text(
        encoding="utf-8"
    )
    api_index = (FRONTEND / "api" / "index.ts").read_text(encoding="utf-8")
    assert "REAUTH_REQUIRED:" not in controller
    assert "BLOCKED:" not in controller
    assert "RECOVERY_REQUIRED:" not in controller
    assert "window.prompt" not in controller
    assert "localStorage" not in controller
    assert "sessionStorage" not in controller
    for moved_responsibility in (
        "subscribeRunEvents",
        "approveAction",
        "modifyAction",
        "resolveRecovery",
        "confirmRun",
        "resumeRun",
    ):
        assert moved_responsibility not in controller
    assert "useRunProjection" in controller
    assert "useActionPlanCommands" in controller
    assert "useRecoveryCommands" in controller
    for symbol in (
        "getRunSnapshot",
        "getRunContext",
        "cancelRun",
        "resumeRun",
        "confirmRun",
        "resolveRecovery",
        "approveAction",
        "rejectAction",
        "modifyAction",
        "prepareRetry",
    ):
        assert f"export function {symbol}" not in api_index
