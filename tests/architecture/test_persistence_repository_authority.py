from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
TESTS = ROOT / "tests"
PERSISTENCE = SRC / "adapters" / "persistence"
PORTS = SRC / "ports" / "persistence"
SQLITE_REPOSITORIES = PERSISTENCE / "sqlite" / "repositories"
LEGACY_REPOSITORY = PERSISTENCE / "repositories.py"
PERSISTENCE_BARREL = PERSISTENCE / "__init__.py"

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

RETIRED_MODULES = (
    PERSISTENCE / "cancel_intent_repository.py",
    PERSISTENCE / "confirmation_run_repository.py",
    PERSISTENCE / "corrective_plan_repository.py",
    PERSISTENCE / "connector_identity.py",
)

RETIRED_CLASSES = {
    "CancelIntentCommandReceiptRepository",
    "SQLiteConfirmationRunRepository",
    "CorrectiveAwareSQLitePlanRepository",
    "ConnectorAwareActionRepository",
    "ConnectorAwareResourceRefRepository",
}

RETIRED_IMPORT_MODULES = {
    "google_work_agent.adapters.persistence.cancel_intent_repository",
    "google_work_agent.adapters.persistence.confirmation_run_repository",
    "google_work_agent.adapters.persistence.corrective_plan_repository",
    "google_work_agent.adapters.persistence.connector_identity",
    "google_work_agent.adapters.persistence.repositories",
}

RETIRED_RELATIVE_MODULES = {
    "cancel_intent_repository",
    "confirmation_run_repository",
    "corrective_plan_repository",
    "connector_identity",
    "repositories",
}

CANONICAL_BEHAVIOR = {
    "run": ("SQLiteRunRepository", "resume_confirmation"),
    "plan": ("SQLitePlanRepository", "insert_draft"),
    "action": ("SQLiteActionRepository", "connector_id_for_action"),
    "resource_ref": ("SQLiteResourceRefRepository", "connector_id_for_resource_ref"),
    "command_receipt": (
        "SQLiteCommandReceiptRepository",
        "has_applied_request_cancel",
    ),
}

REQUIRED_INFRA_EXPORTS = {
    "MigrationFile",
    "MigrationResult",
    "SQLiteUnitOfWork",
    "apply_migrations",
    "calculate_migration_checksum",
    "connect_sqlite",
    "discover_migrations",
    "normalize_migration_bytes",
    "sqlite_unit_of_work_factory",
}

CANONICAL_SQLITE_REPOSITORIES = {
    f"SQLite{symbol}" for symbol in SYMBOLS.values()
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _classes(path: Path) -> set[str]:
    return {
        node.name
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ClassDef)
    }


def _class_methods(path: Path, class_name: str) -> set[str]:
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.name
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    return set()


def _all_exports(path: Path) -> set[str]:
    for node in _tree(path).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            }
    return set()


def _imports_retired_module(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name in RETIRED_IMPORT_MODULES for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return False

    module = node.module or ""
    if module in RETIRED_IMPORT_MODULES:
        return True
    if node.level and module in RETIRED_RELATIVE_MODULES:
        return True
    if node.level and not module:
        return any(alias.name in RETIRED_RELATIVE_MODULES for alias in node.names)
    return False


def _retired_import_offenders(root: Path) -> list[str]:
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if any(_imports_retired_module(node) for node in ast.walk(_tree(path))):
            offenders.append(path.relative_to(ROOT).as_posix())
    return sorted(offenders)


def _expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name.rsplit(".", 1)[-1]
    return aliases


def _resolved_name(node: ast.AST, aliases: dict[str, str]) -> str | None:
    name = _expression_name(node)
    if name is None:
        return None
    return aliases.get(name, name)


def _duplicate_repository_authorities_from_sources(
    sources: dict[str, str],
) -> list[str]:
    """Return statically detectable duplicate concrete repository authorities.

    The canonical concrete itself is allowed. Any differently named direct or
    transitive subclass is not. Repository-named aliases and composition
    wrappers that instantiate a canonical concrete (or one of its subclasses)
    are also rejected.
    """

    class_bases: dict[str, set[str]] = {}
    class_nodes: list[tuple[str, ast.ClassDef, dict[str, str]]] = []
    module_trees: list[tuple[str, ast.Module, dict[str, str]]] = []

    for path, source in sources.items():
        tree = ast.parse(source, filename=path)
        aliases = _import_aliases(tree)
        module_trees.append((path, tree, aliases))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                resolved
                for base in node.bases
                if (resolved := _resolved_name(base, aliases)) is not None
            }
            class_bases.setdefault(node.name, set()).update(bases)
            class_nodes.append((path, node, aliases))

    def descends_from_canonical(class_name: str) -> bool:
        pending = list(class_bases.get(class_name, ()))
        seen: set[str] = set()
        while pending:
            base = pending.pop()
            if base in seen:
                continue
            seen.add(base)
            if base in CANONICAL_SQLITE_REPOSITORIES:
                return True
            pending.extend(class_bases.get(base, ()))
        return False

    authority_names = set(CANONICAL_SQLITE_REPOSITORIES)
    authority_names.update(
        name for name in class_bases if descends_from_canonical(name)
    )

    offenders: set[str] = set()

    for path, node, aliases in class_nodes:
        if node.name not in CANONICAL_SQLITE_REPOSITORIES and descends_from_canonical(node.name):
            offenders.add(f"{path}:{node.name}:subclass")
            continue

        if node.name in CANONICAL_SQLITE_REPOSITORIES or not node.name.endswith("Repository"):
            continue

        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            called = _resolved_name(child.func, aliases)
            if called in authority_names:
                offenders.add(f"{path}:{node.name}:wrapper")
                break

    for path, tree, aliases in module_trees:
        for node in tree.body:
            target_name: str | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target_name = _expression_name(node.targets[0])
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                target_name = _expression_name(node.target)
                value = node.value

            if (
                target_name is None
                or value is None
                or target_name in CANONICAL_SQLITE_REPOSITORIES
                or not target_name.endswith("Repository")
            ):
                continue
            referenced = _resolved_name(value, aliases)
            if referenced in authority_names:
                offenders.add(f"{path}:{target_name}:alias")

    return sorted(offenders)


def _production_persistence_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in PERSISTENCE.rglob("*.py")
    }


def test_assigned_persistence_owners_have_canonical_port_and_sqlite_authority() -> None:
    for owner in OWNERS:
        port_path = PORTS / f"{owner}_repository.py"
        adapter_path = SQLITE_REPOSITORIES / f"{owner}_repository.py"
        assert port_path.is_file(), owner
        assert adapter_path.is_file(), owner
        assert SYMBOLS[owner] in _classes(port_path), owner
        assert f"SQLite{SYMBOLS[owner]}" in _classes(adapter_path), owner


def test_broad_and_confirmed_duplicate_repository_modules_are_retired() -> None:
    assert not LEGACY_REPOSITORY.exists()
    assert [path for path in RETIRED_MODULES if path.exists()] == []


def test_confirmed_duplicate_repository_classes_are_absent_from_production() -> None:
    offenders: dict[str, list[str]] = {name: [] for name in RETIRED_CLASSES}
    for path in PERSISTENCE.rglob("*.py"):
        for class_name in _classes(path):
            if class_name in offenders:
                offenders[class_name].append(path.relative_to(ROOT).as_posix())
    assert offenders == {name: [] for name in RETIRED_CLASSES}


def test_assigned_sqlite_repository_classes_are_declared_once_in_production() -> None:
    class_locations: dict[str, list[Path]] = {
        f"SQLite{symbol}": [] for symbol in SYMBOLS.values()
    }
    for path in PERSISTENCE.rglob("*.py"):
        for class_name in _classes(path):
            if class_name in class_locations:
                class_locations[class_name].append(path)

    for owner, symbol in SYMBOLS.items():
        expected = SQLITE_REPOSITORIES / f"{owner}_repository.py"
        assert class_locations[f"SQLite{symbol}"] == [expected]


def test_no_renamed_or_wrapped_duplicate_sqlite_repository_authority() -> None:
    assert _duplicate_repository_authorities_from_sources(_production_persistence_sources()) == []


def test_duplicate_authority_detector_rejects_direct_and_transitive_subclasses() -> None:
    sources = {
        "direct.py": """
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import SQLiteRunRepository
class AlternateRunRepository(SQLiteRunRepository):
    pass
""",
        "transitive.py": """
class WrappedRunRepository(AlternateRunRepository):
    pass
""",
    }

    assert _duplicate_repository_authorities_from_sources(sources) == [
        "direct.py:AlternateRunRepository:subclass",
        "transitive.py:WrappedRunRepository:subclass",
    ]


def test_duplicate_authority_detector_rejects_alias_and_composition_wrapper() -> None:
    sources = {
        "aliases.py": """
from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import SQLiteRunRepository
RunRepositoryAliasRepository = SQLiteRunRepository

class DelegatingRunRepository:
    def __init__(self, connection):
        self._delegate = SQLiteRunRepository(connection)
""",
    }

    assert _duplicate_repository_authorities_from_sources(sources) == [
        "aliases.py:DelegatingRunRepository:wrapper",
        "aliases.py:RunRepositoryAliasRepository:alias",
    ]


def test_production_does_not_import_retired_repository_modules() -> None:
    assert _retired_import_offenders(SRC) == []


def test_tests_do_not_import_retired_repository_modules() -> None:
    assert _retired_import_offenders(TESTS) == []


def test_parent_persistence_barrel_preserves_infra_without_repository_concretes() -> None:
    exports = _all_exports(PERSISTENCE_BARREL)
    assert REQUIRED_INFRA_EXPORTS <= exports
    assert not {
        name for name in exports if name.startswith("SQLite") and name.endswith("Repository")
    }

    tree = _tree(PERSISTENCE_BARREL)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not {
        name
        for name in imported_names
        if name.startswith("SQLite") and name.endswith("Repository")
    }


def test_production_does_not_import_repository_concretes_from_parent_barrel() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "google_work_agent.adapters.persistence":
                continue
            if any(
                alias.name.startswith("SQLite") and alias.name.endswith("Repository")
                for alias in node.names
            ):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []


def test_canonical_owner_repositories_preserve_retired_wrapper_behavior() -> None:
    for owner, (class_name, method_name) in CANONICAL_BEHAVIOR.items():
        path = SQLITE_REPOSITORIES / f"{owner}_repository.py"
        assert path.is_file(), owner
        assert class_name in _classes(path), owner
        assert method_name in _class_methods(path, class_name), f"{owner}.{method_name}"
