from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
PORTS = SRC / "ports" / "persistence"
SQLITE_REPOSITORIES = SRC / "adapters" / "persistence" / "sqlite" / "repositories"
LEGACY_REPOSITORY = SRC / "adapters" / "persistence" / "repositories.py"
PERSISTENCE_BARREL = SRC / "adapters" / "persistence" / "__init__.py"

OWNERS = (
    "conversation",
    "message",
    "run",
    "plan",
    "action",
    "action_dependency",
    "approval",
    "execution_attempt",
    "verification",
    "resource_ref",
    "evidence",
)

SYMBOLS = {
    "conversation": "ConversationRepository",
    "message": "MessageRepository",
    "run": "RunRepository",
    "plan": "PlanRepository",
    "action": "ActionRepository",
    "action_dependency": "ActionDependencyRepository",
    "approval": "ApprovalRepository",
    "execution_attempt": "ExecutionAttemptRepository",
    "verification": "VerificationRepository",
    "resource_ref": "ResourceRefRepository",
    "evidence": "EvidenceRepository",
}


def _classes(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }


def test_assigned_persistence_owners_have_canonical_port_and_sqlite_authority() -> None:
    for owner in OWNERS:
        port_path = PORTS / f"{owner}_repository.py"
        adapter_path = SQLITE_REPOSITORIES / f"{owner}_repository.py"
        assert port_path.is_file(), owner
        assert adapter_path.is_file(), owner
        assert SYMBOLS[owner] in _classes(port_path), owner
        assert f"SQLite{SYMBOLS[owner]}" in _classes(adapter_path), owner


def test_assigned_persistence_owners_have_no_broad_legacy_concrete_authority() -> None:
    assert not LEGACY_REPOSITORY.exists()

    barrel = PERSISTENCE_BARREL.read_text(encoding="utf-8")
    assert ".repositories import" not in barrel
    for symbol in SYMBOLS.values():
        assert f"SQLite{symbol}" not in barrel


def test_assigned_sqlite_repository_classes_are_declared_once_in_production() -> None:
    class_locations: dict[str, list[Path]] = {
        f"SQLite{symbol}": [] for symbol in SYMBOLS.values()
    }
    for path in (SRC / "adapters" / "persistence").rglob("*.py"):
        for class_name in _classes(path):
            if class_name in class_locations:
                class_locations[class_name].append(path)

    for owner, symbol in SYMBOLS.items():
        expected = SQLITE_REPOSITORIES / f"{owner}_repository.py"
        assert class_locations[f"SQLite{symbol}"] == [expected]


def test_production_does_not_import_removed_broad_repository_module() -> None:
    forbidden = (
        "google_work_agent.adapters.persistence.repositories",
        "from .repositories import",
    )
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
