from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/subgraphs/work_analysis"


def test_broad_work_analysis_semantic_authorities_are_retired() -> None:
    assert not (SRC / "application/orchestration/work_analysis.py").exists()
    assert not (SRC / "application/orchestration/assemble_work_analysis_output.py").exists()
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in (SRC / "application").rglob("*.py")
    )
    assert "class WorkAnalysisAgent" not in production


def test_only_final_v2_result_crosses_into_planning() -> None:
    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    planning_graph = (SRC / "adapters/langgraph/subgraphs/planning/graph.py").read_text(
        encoding="utf-8"
    )
    planning_state = (SRC / "adapters/langgraph/subgraphs/planning/state.py").read_text(
        encoding="utf-8"
    )
    assert '"work_analysis_result": result' in graph
    assert '"analysis_result": result' not in graph
    assert 'state.get("work_analysis_result")' in planning_graph
    assert 'working["work_analysis"]' in planning_graph
    assert "work_analysis: WorkAnalysisResultV2" in planning_state
    assert "work_analysis_result: object" not in planning_state


def test_exact_prompt_split_and_prompt_free_finalizer() -> None:
    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    for prompt_id in (
        "work_analysis.assess_information_gaps",
        "work_analysis.assess_operational_risks",
    ):
        assert graph.count(f'"{prompt_id}"') == 1
    finalizer = (OWNER / "nodes/assemble_work_analysis_node.py").read_text(encoding="utf-8")
    assert "PromptReference" not in finalizer
    assert "StructuredLLMRuntime" not in finalizer
