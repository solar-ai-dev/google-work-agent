from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/google_work_agent"
RU = SRC / "adapters/langgraph/subgraphs/request_understanding"
TR = SRC / "adapters/langgraph/subgraphs/tool_routing"
TR_APP = SRC / "application/agents/tool_routing"
RU_OPERATIONS = ("identify_goal", "detect_ambiguity", "finalize_intent", "validate_intent")
TR_OPERATIONS = ("determine_io_resources", "bind_registry_candidates", "select_tool_if_needed", "finalize_route", "validate_route")


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


def test_tool_routing_has_five_operation_nodes_in_canonical_order() -> None:
    for operation in TR_OPERATIONS:
        path = TR / "nodes" / f"{operation}_node.py"
        assert path.is_file()
        assert operation in _called_names(path)

    graph_source = _source(TR / "graph.py")
    canonical_topology = (
        'graph.add_edge(START, "determine_io_resources")',
        '"bind_registry_candidates": "bind_registry_candidates"',
        'graph.add_edge("bind_registry_candidates", "select_tool_if_needed")',
        'graph.add_edge("select_tool_if_needed", "finalize_route")',
        '"validate_route": "validate_route"',
        'graph.add_edge("validate_route", END)',
    )
    positions = [graph_source.index(fragment) for fragment in canonical_topology]
    assert positions == sorted(positions)


def test_binding_precedes_selection_at_router_boundary() -> None:
    route_source = _source(TR / "routing/route_after_determine_io_resources.py")
    assert 'Literal["confirm", "bind_registry_candidates"]' in route_source
    assert 'return "bind_registry_candidates"' in route_source
    assert 'return "select_tool_if_needed"' not in route_source


def test_selection_consumes_previously_bound_candidate_set_only() -> None:
    selection_path = TR / "nodes/select_tool_if_needed_node.py"
    source = _source(selection_path)
    imports = _imports(selection_path)
    assert "project_selection_input" in _called_names(selection_path)
    assert "binding.output_candidates" in source
    assert "eligible_tool_ids=bound.eligible_tool_ids" in source
    assert not any(name.endswith("bind_registry_candidates") for name in imports)
    assert "ConnectorToolCatalog" not in source
    assert "registry_candidates_for_route" not in source
    assert ".eligible(" not in source


def test_registry_discovery_authority_is_binding_only() -> None:
    binding_source = _source(TR_APP / "bind_registry_candidates.py")
    selection_source = _source(TR / "nodes/select_tool_if_needed_node.py")
    assert "registry_candidates_for_route" in binding_source
    assert "eligible_tool_ids" in binding_source
    assert "registry_candidates_for_route" not in selection_source
    assert "tool_catalog" not in selection_source


def test_preselected_or_selected_tool_cannot_bypass_bound_eligibility() -> None:
    finalization_source = _source(TR_APP / "finalize_route.py")
    assert "selected_tool_id not in bound.eligible_tool_ids" in finalization_source
    assert "selected tool is outside the bound eligible set" in finalization_source
    assert "validate_route(plan, tool_catalog=tool_catalog)" in finalization_source


def test_final_validation_runs_after_selection_and_finalization() -> None:
    graph_source = _source(TR / "graph.py")
    selection_edge = graph_source.index('graph.add_edge("select_tool_if_needed", "finalize_route")')
    validation_edge = graph_source.index('"validate_route": "validate_route"')
    terminal_edge = graph_source.index('graph.add_edge("validate_route", END)')
    assert selection_edge < validation_edge < terminal_edge
    assert "validate_route(" in _source(TR / "nodes/validate_route_node.py")


def test_downstream_tool_reselection_authority_is_absent_in_tool_routing() -> None:
    selection_path = TR / "nodes/select_tool_if_needed_node.py"
    for path in (TR / "nodes").glob("*_node.py"):
        if path == selection_path:
            continue
        assert "select_tool_if_needed(" not in _source(path)
        assert "registry_candidates_for_route(" not in _source(path)


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
    assert {path.stem for path in (TR / "projections").glob("*_projection.py")} == {"determine_io_resources_projection", "semantic_candidate_projection", "selection_projection", "binding_projection", "result_projection"}


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
