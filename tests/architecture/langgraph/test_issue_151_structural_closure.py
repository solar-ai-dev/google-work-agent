from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src/google_work_agent"
LANGGRAPH = SRC / "adapters/langgraph"

OWNED_SYMBOLS = {
    "main/state.py": "MultiAgentGraphStateV2",
    "registry/node_registry.py": "NodeRegistry",
    "registry/resume_target_registry.py": "ResumeTargetRegistry",
    "profiles/profile_registry.py": "get_graph_profile_builder",
    "profiles/single_baseline.py": "build_single_baseline_graph",
    "profiles/three_stage.py": "build_three_stage_graph",
    "profiles/six_role_baseline.py": "build_six_role_baseline_graph",
    "main/nodes/retrieval_entry_node.py": "retrieval_entry_node",
    "main/nodes/planning_entry_node.py": "planning_entry_node",
    "main/nodes/review_entry_node.py": "review_entry_node",
    "main/nodes/cancel_resolution_node.py": "cancel_resolution_node",
    "main/nodes/initialize_node.py": "initialize_node",
    "main/nodes/domain_validation_node.py": "domain_validation_node",
    "main/nodes/preflight_node.py": "preflight_node",
    "main/nodes/domain_reconcile_node.py": "domain_reconcile_node",
    "main/nodes/action_execution_node.py": "action_execution_node",
    "main/nodes/verification_node.py": "verification_node",
    "main/nodes/recovery_node.py": "recovery_node",
    "main/nodes/response_synthesis_node.py": "response_synthesis_node",
    "main/nodes/terminal_commit_node.py": "terminal_commit_node",
    "main/nodes/finalize_node.py": "finalize_node",
}

ROOT_HELPERS = {
    "__init__.py",
    "agent_kernel.py",
    "checkpoint_control.py",
    "checkpoint_secret_boundary.py",
    "confirmation_llm_runtime.py",
    "corrective_plan_persistence.py",
    "corrective_plan_reachability.py",
    "invocation.py",
    "pre_analysis_composition.py",
    "subgraph_state.py",
    "write_execution.py",
    "write_execution_driver.py",
    "write_reconciliation.py",
    "write_recovery.py",
}


def _declared_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_all_issue_owned_ledger_symbols_exist_at_the_exact_paths() -> None:
    for relative_path, symbol in OWNED_SYMBOLS.items():
        path = LANGGRAPH / relative_path
        assert path.is_file(), relative_path
        assert symbol in _declared_symbols(path), relative_path


def test_main_graph_state_and_registries_each_have_one_production_authority() -> None:
    definitions = {
        symbol: [] for symbol in ("MultiAgentGraphStateV2", "NodeRegistry", "ResumeTargetRegistry")
    }
    for path in SRC.rglob("*.py"):
        declared = _declared_symbols(path)
        for symbol in definitions:
            if symbol in declared:
                definitions[symbol].append(path.relative_to(SRC).as_posix())

    assert definitions == {
        "MultiAgentGraphStateV2": ["adapters/langgraph/main/state.py"],
        "NodeRegistry": ["adapters/langgraph/registry/node_registry.py"],
        "ResumeTargetRegistry": ["adapters/langgraph/registry/resume_target_registry.py"],
    }
    main_graph_builders = [
        path.relative_to(SRC).as_posix()
        for path in (LANGGRAPH / "main").rglob("*.py")
        if "StateGraph(GraphState)" in path.read_text(encoding="utf-8")
    ]
    assert main_graph_builders == ["adapters/langgraph/main/graph.py"]


def test_root_langgraph_helpers_are_closed_and_have_no_dead_compatibility_facade() -> None:
    assert {path.name for path in LANGGRAPH.glob("*.py")} == ROOT_HELPERS
    production_source = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py"))
    assert "ConnectorBoundCompleteReadActionHandler" not in production_source
    assert "connector_read_result" not in production_source


def test_retrieval_exact_routers_are_the_only_compiled_edge_authorities() -> None:
    source = (LANGGRAPH / "subgraphs/retrieval/graph.py").read_text(encoding="utf-8")
    assert '"assess_sufficiency",\n            route_after_assess_sufficiency,' in source
    assert '"finalize",\n            route_after_finalize_retrieval,' in source
    assert "def _route_after_sufficiency" not in source
    assert "def _route_after_finalize" not in source
