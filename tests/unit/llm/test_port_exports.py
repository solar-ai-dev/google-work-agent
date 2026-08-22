"""Static structural closure tests for the canonical LLM Port owner package."""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
ROOT_PORTS_INIT = REPO_ROOT / "src" / "google_work_agent" / "ports" / "__init__.py"
OWNER_INIT = REPO_ROOT / "src" / "google_work_agent" / "ports" / "llm" / "__init__.py"
OWNER_CONTRACTS = REPO_ROOT / "src" / "google_work_agent" / "ports" / "llm" / "contracts.py"
LEGACY_LLM_MODULE = REPO_ROOT / "src" / "google_work_agent" / "ports" / "llm.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imported_symbols(path: Path, module: str) -> set[str]:
    for node in _parse(path).body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return {alias.name for alias in node.names}
    raise AssertionError(f"{path} does not import {module}")


def _exported_symbols(path: Path) -> set[str]:
    for node in _parse(path).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            raise AssertionError("__all__ must be a literal list or tuple")
        values = set()
        for item in node.value.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise AssertionError("__all__ entries must be literal strings")
            values.add(item.value)
        return values
    raise AssertionError(f"{path} does not define __all__")


def _defined_contract_symbols(path: Path) -> set[str]:
    return {node.name for node in _parse(path).body if isinstance(node, ast.ClassDef)}


def test_llm_port_exports__root_requested_symbols__match_owner_exports() -> None:
    requested = _imported_symbols(ROOT_PORTS_INIT, "google_work_agent.ports.llm")
    owner_imports = _imported_symbols(OWNER_INIT, "google_work_agent.ports.llm.contracts")

    assert "ActualRuntime" in requested
    assert requested == owner_imports
    assert requested == _exported_symbols(OWNER_INIT)
    assert requested <= _exported_symbols(ROOT_PORTS_INIT)


def test_llm_port_exports__owner_exports__have_canonical_definitions() -> None:
    requested = _imported_symbols(ROOT_PORTS_INIT, "google_work_agent.ports.llm")

    assert requested <= _defined_contract_symbols(OWNER_CONTRACTS)


def test_llm_port_exports__legacy_shadow_module__removed() -> None:
    assert not LEGACY_LLM_MODULE.exists()
