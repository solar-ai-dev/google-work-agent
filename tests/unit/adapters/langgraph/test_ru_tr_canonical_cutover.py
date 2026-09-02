from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/google_work_agent"
RU = SRC / "adapters/langgraph/subgraphs/request_understanding"
TR = SRC / "adapters/langgraph/subgraphs/tool_routing"
TR_APP = SRC / "application/agents/tool_routing"
RU_OPERATIONS = ("identify_goal", "detect_ambiguity", "finalize_intent", "validate_intent")
TR_OPERATIONS = (
    "determine_io_resources",
    "bind_registry_candidates",
    "select_tool_if_needed",
    "finalize_route",
    "validate_route",
)


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


def test_request_understanding_has__three_runtime_nodes__for_four_operations() -> None:
    for operation in ("identify_goal", "detect_ambiguity", "finalize_intent"):
        path = RU / "nodes" / f"{operation}_node.py"
        assert path.is_file()
        assert operation in _called_names(path)
    assert "validate_intent" in _called_names(
        SRC / "application/agents/request_understanding/finalize_intent.py"
    )
    assert not (RU / "nodes/validate_intent_node.py").exists()


def test_tool_routing_has__five_operation_nodes__in_canonical_order() -> None:
    for operation in TR_OPERATIONS:
        path = TR / "nodes" / f"{operation}_node.py"
        assert path.is_file()
        assert operation in _called_names(path)

    graph_source = _source(TR / "graph.py")
    canonical_topology = (
        'graph.add_edge(START, "determine_io_resources")',
        '"bind_registry_candidates": "bind_registry_candidates"',
        'graph.add_conditional_edges(\n            "bind_registry_candidates"',
        'graph.add_conditional_edges(\n            "select_tool_if_needed"',
        '"validate_route": "validate_route"',
        'graph.add_conditional_edges("validate_route"',
    )
    positions = [graph_source.index(fragment) for fragment in canonical_topology]
    assert positions == sorted(positions)
    tree = _tree(TR / "graph.py")
    graph_nodes = [
        call.args[0].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "add_node"
        and call.args
        and isinstance(call.args[0], ast.Constant)
    ]
    assert graph_nodes == list(TR_OPERATIONS)
    assert "prepare_confirmation" not in graph_source
    assert 'add_node("confirm"' not in graph_source


def test_binding_precedes__selection_at__router_boundary() -> None:
    route_source = _source(TR / "routing/route_after_determine_io_resources.py")
    assert 'Literal["finalize_route", "bind_registry_candidates"]' in route_source
    assert 'return "bind_registry_candidates"' in route_source
    assert 'return "select_tool_if_needed"' not in route_source


def test_selection_consumes__previously_bound__candidate_set_only() -> None:
    selection_path = TR / "nodes/select_tool_if_needed_node.py"
    source = _source(selection_path)
    imports = _imports(selection_path)
    assert "project_select_tool_if_needed_input" in _called_names(selection_path)
    assert 'projection["registry_candidates"]' in source
    assert "eligible_tool_ids=bound.eligible_tool_ids" in source
    assert not any(name.endswith("bind_registry_candidates") for name in imports)
    assert "SignedToolRegistry" not in source
    assert "registry_candidates_for_route" not in source
    assert ".eligible(" not in source


def test_registry_discovery__authority_is__binding_only() -> None:
    binding_source = _source(TR_APP / "bind_registry_candidates.py")
    selection_source = _source(TR / "nodes/select_tool_if_needed_node.py")
    assert "registry_candidates_for_route" in binding_source
    assert "eligible_tool_ids" in binding_source
    assert "registry_candidates_for_route" not in selection_source
    assert "tool_catalog" not in selection_source


def test_preselected_or__selected_tool_cannot__bypass_bound_eligibility() -> None:
    finalization_source = _source(TR_APP / "finalize_route.py")
    assert "selected_tool_id not in bound.eligible_tool_ids" in finalization_source
    assert "selected tool is outside the bound eligible set" in finalization_source
    assert "validate_route(plan, tool_catalog=tool_catalog)" in finalization_source


def test_final_validation__runs_after__selection_and_finalization() -> None:
    graph_source = _source(TR / "graph.py")
    selection_edge = graph_source.index(
        'graph.add_conditional_edges(\n            "select_tool_if_needed"'
    )
    validation_edge = graph_source.index('"validate_route": "validate_route"')
    terminal_edge = graph_source.index('graph.add_conditional_edges("validate_route"')
    assert selection_edge < validation_edge < terminal_edge
    assert "validate_route(" in _source(TR / "nodes/validate_route_node.py")


def test_downstream_tool_reselection__authority_is_absent__in_tool_routing() -> None:
    selection_path = TR / "nodes/select_tool_if_needed_node.py"
    for path in (TR / "nodes").glob("*_node.py"):
        if path == selection_path:
            continue
        assert "select_tool_if_needed(" not in _source(path)
        assert "registry_candidates_for_route(" not in _source(path)


def test_obsolete_broad__module_authorities__are_absent() -> None:
    for path in (
        SRC / "adapters/langgraph/subgraphs/request_understanding.py",
        SRC / "adapters/langgraph/subgraphs/tool_routing.py",
    ):
        assert not path.exists()


def test_nodes_have__no_forbidden__execution_dependencies() -> None:
    forbidden = (
        ".retrieval",
        ".work_analysis",
        ".planning",
        ".review",
        ".persistence",
        ".repositories",
        ".mcp",
        ".connectors",
        ".providers",
    )
    for owner in (RU, TR):
        for path in (owner / "nodes").glob("*_node.py"):
            for imported in _imports(path):
                assert not any(fragment in imported for fragment in forbidden), (path, imported)


def test_no_agent__to_agent__imports() -> None:
    owners = {
        "request_understanding",
        "tool_routing",
        "retrieval",
        "work_analysis",
        "planning",
        "review",
    }
    for owner_name, owner in (("request_understanding", RU), ("tool_routing", TR)):
        for path in owner.rglob("*.py"):
            for imported in _imports(path):
                if ".adapters.langgraph.subgraphs." not in imported:
                    continue
                imported_owner = imported.split(".subgraphs.", 1)[1].split(".", 1)[0]
                assert imported_owner not in owners - {owner_name}


def test_tool_routing_has__no_downstream_or__provider_execution_calls() -> None:
    forbidden_calls = {
        "execute",
        "invoke_tool",
        "call_tool",
        "mcp_call",
        "retrieve",
        "search_provider",
        "mutate",
        "save",
        "commit",
    }
    for path in (TR / "nodes").glob("*_node.py"):
        assert _called_names(path).isdisjoint(forbidden_calls)


def test_projection_allowlists__are_owner__local() -> None:
    assert {path.stem for path in (RU / "projections").glob("*_projection.py")} == {
        "identify_goal_projection",
        "detect_ambiguity_projection",
        "finalize_intent_projection",
    }
    assert {path.stem for path in (TR / "projections").glob("*_projection.py")} == {
        "determine_io_resources_projection",
        "bind_registry_candidates_projection",
        "select_tool_if_needed_projection",
        "finalize_route_projection",
        "validate_route_projection",
    }


def test_node_patches__do_not__spread_main_state() -> None:
    for owner in (RU, TR):
        for path in (owner / "nodes").glob("*_node.py"):
            source = _source(path)
            assert "{**state" not in source
            assert "dict(state)" not in source


def test_canonical_application__operations__exist() -> None:
    for operation in RU_OPERATIONS:
        assert (SRC / "application/agents/request_understanding" / f"{operation}.py").is_file()
    for operation in TR_OPERATIONS:
        assert (SRC / "application/agents/tool_routing" / f"{operation}.py").is_file()
