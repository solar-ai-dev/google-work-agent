import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/main"


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_exact_terminal_control_files_and_functions_are_distinct() -> None:
    expected = {
        "response_synthesis_node.py": "response_synthesis_node",
        "terminal_commit_node.py": "terminal_commit_node",
        "finalize_node.py": "finalize_node",
    }
    for filename, function in expected.items():
        path = OWNER / "nodes" / filename
        assert path.is_file()
        assert function in _function_names(path)

    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    assert '"response_synthesis": self.finalize' not in graph
    assert '"terminal_commit": "terminal_commit"' in graph
    assert "response_synthesis: Any" in graph
    assert "terminal_commit: Any" in graph
    assert "finalize: Any" in graph


def test_terminal_nodes_have_no_product_llm_provider_or_persistence_authority() -> None:
    for filename in (
        "response_synthesis_node.py",
        "terminal_commit_node.py",
        "finalize_node.py",
    ):
        source = (OWNER / "nodes" / filename).read_text(encoding="utf-8")
        assert "ports.llm" not in source
        assert "adapters.connectors" not in source
        assert "adapters.persistence" not in source
        assert "UnitOfWork" not in source
        assert "PromptReference" not in source


def test_broad_finalize_handler_and_direct_finalize_routes_are_retired() -> None:
    workflow = (OWNER / "workflow.py").read_text(encoding="utf-8")
    response = (OWNER / "response_synthesis.py").read_text(encoding="utf-8")
    assert "def _finalize_node" not in workflow
    assert "def _finalize_node" not in response
    assert workflow.count("self._block_run(") == 1
    assert '"__target__": "finalize"' not in workflow


def test_terminal_controls_are_not_resume_targets() -> None:
    registry = (SRC / "adapters/langgraph/registry/node_registry.py").read_text(
        encoding="utf-8"
    )
    for node in ("RESPONSE_SYNTHESIS", "TERMINAL_COMMIT", "FINALIZE"):
        assert f'MainResumeStageIdV1.{node}' not in registry
