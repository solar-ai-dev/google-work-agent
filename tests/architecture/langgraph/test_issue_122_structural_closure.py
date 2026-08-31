from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

from google_work_agent.adapters.langgraph.main.graph import (
    GraphNodeBindings,
    MainControlNodeBindings,
)
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    MAIN_RESUME_STAGES,
)

ROOT = Path(__file__).resolve().parents[3]
NODE_ROOT = ROOT / "src/google_work_agent/adapters/langgraph/main/nodes"
EXPECTED = {
    "cancel_resolution_node.py": "cancel_resolution_node",
    "action_execution_node.py": "action_execution_node",
    "verification_node.py": "verification_node",
    "recovery_node.py": "recovery_node",
}


def test_exact_four_external_effect_control_paths_and_symbols_exist() -> None:
    for filename, symbol in EXPECTED.items():
        tree = ast.parse((NODE_ROOT / filename).read_text(encoding="utf-8"))
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert symbol in functions


def test_external_effect_controls_use_main_control_bindings_only() -> None:
    control_fields = {field.name for field in fields(MainControlNodeBindings)}
    broad_fields = {field.name for field in fields(GraphNodeBindings)}
    assert {"cancel_resolution", "action_execution", "verification", "recovery"} <= control_fields
    assert not {"cancel_resolution", "action_execution", "verification", "recovery"} & broad_fields


def test_owned_resume_set_is_exact_and_action_execution_is_not_resumable() -> None:
    assert {"READ_EXECUTION", "VERIFICATION", "RECOVERY", "CANCEL_RESOLUTION"} <= (
        MAIN_RESUME_STAGES
    )
    assert "ACTION_EXECUTION" not in MAIN_RESUME_STAGES


def test_control_nodes_have_no_direct_semantic_or_external_authority() -> None:
    forbidden = (
        "google_work_agent.domain",
        "google_work_agent.ports.persistence",
        "google_work_agent.adapters.persistence",
        "google_work_agent.adapters.connectors",
        "google_work_agent.ports.connector",
        "google_work_agent.ports.llm",
        "PromptRef",
    )
    for filename in EXPECTED:
        source = (NODE_ROOT / filename).read_text(encoding="utf-8")
        assert not any(item in source for item in forbidden), filename


def test_cancel_intent_has_one_receipt_backed_runtime_seam() -> None:
    runtime_root = ROOT / "src/google_work_agent/adapters/langgraph/main"
    definitions: list[tuple[str, str]] = []
    for path in runtime_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        definitions.extend(
            (path.name, node.name)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_has_persisted_cancel_intent"
        )
    assert definitions == [("artifact_freshness.py", "_has_persisted_cancel_intent")]
    authority = (runtime_root / "artifact_freshness.py").read_text(encoding="utf-8")
    assert "unit_of_work.command_receipts" in authority
    assert "unit_of_work.audits" not in authority
