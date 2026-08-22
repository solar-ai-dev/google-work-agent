"""Architecture gates for B-API-2 canonical API ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = (
    ROOT / "src/google_work_agent/api/routes/runs.py",
    ROOT / "src/google_work_agent/api/routes/conversations.py",
    ROOT / "src/google_work_agent/api/routes/events.py",
)
USE_CASE_ROOT = ROOT / "src/google_work_agent/application/use_cases"
OWNERS = ("run", "conversation", "message")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_owned_routes_do_not_call_broad_legacy_semantic_services() -> None:
    forbidden = (".query_service().", ".start_run_service()(", ".cancel_run_service()(", ".resume_run_service()(", ".resolve_recovery_service()(", ".create_conversation_service()(", "application.queries import", "application.start_run import", "application.write_actions import")
    for path in ROUTES:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: forbidden route authority {token}"


def test_owned_routes_do_not_traverse_uow_or_mutate_domain_directly() -> None:
    forbidden = ("unit_of_work", ".runs.", ".plans.", ".actions.", ".approvals.", "sqlite3", "adapters.persistence")
    for path in ROUTES:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: route owns persistence/domain {token}"


def test_canonical_handlers_do_not_reverse_depend_on_api_or_provider_concretes() -> None:
    forbidden_prefixes = ("fastapi", "google_work_agent.api", "google_work_agent.adapters.persistence.sqlite", "google_work_agent.adapters.connectors.google", "googleapiclient", "google.oauth2")
    for owner in OWNERS:
        for path in (USE_CASE_ROOT / owner).glob("*.py"):
            for imported in _imports(path):
                assert not imported.startswith(forbidden_prefixes), f"{path}: reverse/concrete dependency {imported}"


def test_canonical_handlers_do_not_delegate_to_broad_legacy_authorities() -> None:
    forbidden = {"google_work_agent.application.queries", "google_work_agent.application.start_run", "google_work_agent.application.conversation_lifecycle", "google_work_agent.application.run_lifecycle", "google_work_agent.application.write_actions", "google_work_agent.application.write_cancellation", "google_work_agent.application.write_recovery"}
    for owner in OWNERS:
        for path in (USE_CASE_ROOT / owner).glob("*.py"):
            assert not (_imports(path) & forbidden), f"{path}: canonical handler delegates to legacy authority"


def test_event_route_keeps_transport_but_not_replay_fallback_semantics() -> None:
    source = (ROOT / "src/google_work_agent/api/routes/events.py").read_text(encoding="utf-8")
    assert "StreamingResponse" in source
    assert "_format_sse" in source
    assert ".subscribe(" in source
    assert "keepalive" in source
    assert ".replay(" not in source
    assert "SnapshotRequiredReplayError" not in source
    assert "InvalidReplayCursorError" not in source
    assert "build_snapshot_required_event" not in source
    assert "GetEventReplayHandler" in source
