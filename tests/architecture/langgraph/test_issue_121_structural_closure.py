from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.main.state import (
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    MAIN_RESUME_STAGES,
)

ROOT = Path(__file__).resolve().parents[3]
NODE_ROOT = ROOT / "src/google_work_agent/adapters/langgraph/main/nodes"
EXPECTED = {
    "retrieval_entry_node.py": "retrieval_entry_node",
    "planning_entry_node.py": "planning_entry_node",
    "review_entry_node.py": "review_entry_node",
    "initialize_node.py": "initialize_node",
    "domain_validation_node.py": "domain_validation_node",
    "preflight_node.py": "preflight_node",
    "domain_reconcile_node.py": "domain_reconcile_node",
}


def test_exact_seven_control_paths_and_symbols_exist() -> None:
    assert set(EXPECTED) <= {path.name for path in NODE_ROOT.glob("*_node.py")}
    for filename, symbol in EXPECTED.items():
        tree = ast.parse((NODE_ROOT / filename).read_text(encoding="utf-8"))
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert symbol in functions


def test_exact_controls_are_removed_from_broad_bindings() -> None:
    assert {
        "initialize",
        "retrieval_entry",
        "planning_entry",
        "review_entry",
        "domain_validation",
        "preflight",
        "domain_reconcile",
    } <= {field.name for field in fields(MainControlNodeBindings)}
    assert not {
        "initialize",
        "retrieval_entry",
        "planning_entry",
        "review_entry",
        "domain_validation",
        "preflight",
        "domain_reconcile",
        "modify_review",
    } & {field.name for field in fields(GraphNodeBindings)}


def test_control_nodes_have_no_direct_business_or_infrastructure_imports() -> None:
    forbidden = (
        "google_work_agent.domain",
        "google_work_agent.ports.persistence",
        "google_work_agent.adapters.persistence",
        "google_work_agent.adapters.connectors",
        "google_work_agent.ports.llm",
    )
    for path in NODE_ROOT.glob("*_node.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(module in source for module in forbidden), path.name


def test_resume_and_phase_namespaces_remain_separate() -> None:
    assert {"RETRIEVAL_ENTRY", "PLANNING_ENTRY", "REVIEW_ENTRY", "PREFLIGHT"} <= (
        MAIN_RESUME_STAGES
    )
    assert "INITIALIZE" not in MAIN_RESUME_STAGES
    assert "DOMAIN_VALIDATION" not in MAIN_RESUME_STAGES
    assert "DOMAIN_RECONCILE" not in {phase.value for phase in WorkflowPhase}
