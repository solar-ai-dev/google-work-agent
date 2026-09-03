from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
MAPPING_SOURCE = (
    ROOT
    / "docs"
    / "canonical"
    / "16-repository-architecture"
    / "01-spec-to-code-deterministic-mapping.md"
)
DIRECTORY_SOURCE = (
    ROOT / "docs" / "canonical" / "16-repository-architecture" / "02-directory-ownership.md"
)


def _symbols(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in module.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _section(markdown: str, heading: str, next_heading: str) -> str:
    _, separator, tail = markdown.partition(heading)
    assert separator, f"missing canonical manifest heading: {heading}"
    return tail.partition(next_heading)[0]


def _table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        if not line.startswith("|") or "---" in line:
            continue
        cells: list[str] = []
        current: list[str] = []
        in_code = False
        for character in line.strip("|"):
            if character == "`":
                in_code = not in_code
            if character == "|" and not in_code:
                cells.append("".join(current).strip())
                current = []
            else:
                current.append(character)
        cells.append("".join(current).strip())
        if cells and cells[0] not in {"Spec term", "Spec/API capability", "Responsibility"}:
            rows.append(cells)
    return rows


def _application_manifest_from_source() -> dict[str, set[str]]:
    markdown = MAPPING_SOURCE.read_text(encoding="utf-8")
    core = _section(markdown, "### Application capability mapping", "### Run lifecycle closure")
    local = _section(
        markdown,
        "### Local API boundary capability manifest",
        "### Provider-neutral Application rule",
    )
    manifest: dict[str, set[str]] = {}
    for cells in _table_rows(core):
        owner = cells[1].strip("`")
        operations = re.findall(r"`([a-z][a-z0-9_]*)`", cells[3])
        manifest.setdefault(owner, set()).update(operations)
    for cells in _table_rows(local):
        owner = cells[1].strip("`")
        operations = re.findall(r"`([a-z][a-z0-9_]*)`", cells[2])
        manifest.setdefault(owner, set()).update(operations)
    assert manifest and all(manifest.values()), "empty canonical Application manifest"
    return manifest


def _agent_manifest_from_source() -> dict[str, tuple[str, ...]]:
    markdown = MAPPING_SOURCE.read_text(encoding="utf-8")
    section = _section(markdown, "### Agent capability mapping", "### Runtime Node ID")
    block = section.split("```", 2)[1]
    manifest: dict[str, list[str]] = {}
    owner: str | None = None
    for line in block.splitlines():
        if line.endswith("/"):
            owner = line.removesuffix("/")
            manifest[owner] = []
        elif owner is not None and line.startswith("  "):
            manifest[owner].append(line.strip())
    assert manifest and all(manifest.values()), "empty canonical Agent manifest"
    return {key: tuple(value) for key, value in manifest.items()}


def _launcher_manifest_from_source() -> set[tuple[str, tuple[str, ...], str]]:
    markdown = DIRECTORY_SOURCE.read_text(encoding="utf-8")
    section = _section(markdown, "#### Launcher runtime", "#### Windows installer")
    manifest: set[tuple[str, tuple[str, ...], str]] = set()
    for cells in _table_rows(section):
        filename = cells[1].strip("`").removeprefix("launcher/")
        symbols = tuple(
            symbol.strip().removesuffix("()") for symbol in re.findall(r"`([^`]+)`", cells[2])
        )
        test_owner = cells[3].strip("`")
        manifest.add((filename, symbols, test_owner))
    assert manifest, "empty canonical Launcher manifest"
    return manifest


def _has_asserting_test(path: Path) -> bool:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for function in (
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ):
        if any(isinstance(node, ast.Assert) for node in ast.walk(function)):
            return True
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"raises", "fail"}
            for node in ast.walk(function)
        ):
            return True
    return False


def _handler_symbol(operation: str) -> str:
    return "".join(part.capitalize() for part in operation.split("_")) + "Handler"


def _assert_mapping(production: Path, symbols: tuple[str, ...], test_owner: Path) -> None:
    assert production.is_file(), (
        f"missing canonical production owner: {production.relative_to(ROOT)}"
    )
    assert set(symbols) <= _symbols(production), (
        f"missing canonical symbol: {production.relative_to(ROOT)}::{symbols}"
    )
    assert test_owner.is_file(), f"missing canonical test owner: {test_owner.relative_to(ROOT)}"
    assert _has_asserting_test(test_owner), (
        f"canonical test owner has no asserting test: {test_owner.relative_to(ROOT)}"
    )


def test_required_application__manifest_has__exact_production_and_test_owners() -> None:
    for owner, operations in _application_manifest_from_source().items():
        for operation in operations:
            _assert_mapping(
                SRC / "application" / "use_cases" / owner / f"{operation}.py",
                (_handler_symbol(operation),),
                ROOT
                / "tests"
                / "unit"
                / "application"
                / "use_cases"
                / owner
                / f"test_{operation}.py",
            )


def test_required_agent__manifest_has__exact_production_and_test_owners() -> None:
    for owner, operations in _agent_manifest_from_source().items():
        for operation in operations:
            _assert_mapping(
                SRC / "application" / "agents" / owner / f"{operation}.py",
                (operation,),
                ROOT / "tests" / "unit" / "application" / "agents" / owner / f"test_{operation}.py",
            )


def test_launcher_runtime__manifest_has__exact_production_and_test_owners() -> None:
    for filename, symbols, test_path in _launcher_manifest_from_source():
        _assert_mapping(ROOT / "launcher" / filename, symbols, ROOT / test_path)
