"""Structural closure tests for the canonical LLM Port owner package."""

from __future__ import annotations

import ast
from pathlib import Path

import google_work_agent.ports.llm as llm_ports


ROOT_PORTS_INIT = Path(__file__).parents[3] / "src" / "google_work_agent" / "ports" / "__init__.py"
LEGACY_LLM_MODULE = Path(__file__).parents[3] / "src" / "google_work_agent" / "ports" / "llm.py"


def _root_llm_requested_symbols() -> set[str]:
    tree = ast.parse(ROOT_PORTS_INIT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "google_work_agent.ports.llm":
            return {alias.name for alias in node.names}
    raise AssertionError("root ports barrel does not import the LLM owner package")


def test_llm_port_exports__root_requested_symbols__all_resolve_from_owner_package() -> None:
    requested = _root_llm_requested_symbols()

    assert requested == set(llm_ports.__all__)
    assert all(hasattr(llm_ports, symbol) for symbol in requested)


def test_llm_port_exports__canonical_definitions__owned_by_llm_package() -> None:
    requested = _root_llm_requested_symbols()

    assert all(
        getattr(llm_ports, symbol).__module__ == "google_work_agent.ports.llm.contracts"
        for symbol in requested
    )


def test_llm_port_exports__legacy_shadow_module__removed() -> None:
    assert not LEGACY_LLM_MODULE.exists()
