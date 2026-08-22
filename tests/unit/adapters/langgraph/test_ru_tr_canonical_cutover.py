from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/google_work_agent"
RU = SRC / "adapters/langgraph/subgraphs/request_understanding"
TR = SRC / "adapters/langgraph/subgraphs/tool_routing"
RU_OPERATIONS = ("identify_goal", "detect_ambiguity", "finalize_intent", "validate_intent")
TR_OPERATIONS = ("determine_io_resources", "select_tool_if_needed", "bind_registry_candidates", "finalize_route", "validate_route")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.AST:
    return ast.parse(_source(path), filename=str(path))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _called_names(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def test_request_understanding_has_four_operation_nodes() -> None:
    for operation in RU_OPERATIONS:
        path = RU / "nodes" / f"{operation}_node.py"
        assert path.is_file()
        assert operation in _called_names(path)


def test_tool_routing_has_five_operation_nodes() -> None:
    for operation in TR_OPERATIONS:
        path = TR / "nodes" / f"{operation}_node.py"
        assert path.is_file()
        assert operation in _called_names(path)


def test_broad_modules_are_compatibility_only() -> None:
    for path in (SRC / "adapters/langgraph/subgraphs/request_understanding.py", SRC / "adapters/langgraph/subgraphs/tool_routing.py"):
        assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in _tree(path).body)


def test_nodes_have_no_forbidden_execution_dependencies() -> None:
    forbidden = (".retrieval", ".work_analysis", ".planning", ".review", ".persistence", ".repositories", ".mcp", ".connectors", ".providers")
    for owner in (RU, TR):
        for path in (owner / "nodes").glob("*_node.py"):
            for imported in _imports(path):
                assert not any(fragment in imported for fragment in forbidden), (path, imported)


def test_no_agent_to_agent_imports() -> None:
    owners = {"request_understanding", "tool_routing", "retrieval", "work_analysis", "planning", "review"}
    for owner_name, owner in (("request_understanding", RU), ("tool_routing", TR)):
        for path in owner.rglob("*.py"):
            for imported in _imports(path):
                if ".adapters.langgraph.subgraphs." not in imported:
                    continue
                imported_owner = imported.split(".subgraphs.", 1)[1].split(".", 1)[0]
                assert imported_owner not in owners - {owner_name}


def test_tool_routing_has_no_downstream_or_provider_execution_calls() -> None:
    forbidden_calls = {"execute", "invoke_tool", "call_tool", "mcp_call", "retrieve", "search_provider", "mutate", "save", "commit"}
    for path in (TR / "nodes").glob("*_node.py"):
        assert _called_names(path).isdisjoint(forbidden_calls)


def test_projection_allowlists_are_owner_local() -> None:
    assert {path.stem for path in (RU / "projections").glob("*_projection.py")} == {"request_projection", "candidate_projection", "intent_projection"}
    assert {path.stem for path in (TR / "projections").glob("*_projection.py")} == {"determine_io_resources_projection", "semantic_candidate_projection", "binding_projection", "result_projection"}


def test_node_patches_do_not_spread_main_state() -> None:
    for owner in (RU, TR):
        for path in (owner / "nodes").glob("*_node.py"):
            source = _source(path)
            assert "{**state" not in source
            assert "dict(state)" not in source


def test_canonical_application_operations_exist() -> None:
    for operation in RU_OPERATIONS:
        assert (SRC / "application/agents/request_understanding" / f"{operation}.py").is_file()
    for operation in TR_OPERATIONS:
        assert (SRC / "application/agents/tool_routing" / f"{operation}.py").is_file()
