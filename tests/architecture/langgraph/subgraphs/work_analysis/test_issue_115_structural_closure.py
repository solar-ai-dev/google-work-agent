from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "src/google_work_agent"
OWNER = SRC / "adapters/langgraph/subgraphs/work_analysis"


def test_production_graph_uses_four_exact_prompts_and_no_broad_prompt() -> None:
    graph = (OWNER / "graph.py").read_text(encoding="utf-8")
    prompt_ids = (
        "work_analysis.extract_work_facts",
        "work_analysis.resolve_entity_relations",
        "work_analysis.resolve_temporal_dependencies",
        "work_analysis.detect_duplicate_conflict_candidates",
    )
    assert all(graph.count(f'"{prompt_id}"') == 1 for prompt_id in prompt_ids)
    assert 'load_prompt_reference("work_analysis.analyze"' not in graph

    main = (SRC / "adapters/langgraph/main/workflow.py").read_text(encoding="utf-8")
    assert "subgraphs.work_analysis.graph" in main
    assert "WorkAnalysisAgent" not in main


def test_validate_relations_is_deterministic_and_not_in_successor_projection() -> None:
    validator = (SRC / "application/agents/work_analysis/validate_relations.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("StructuredLLMRuntime", "PromptReference", "load_prompt_reference"):
        assert forbidden not in validator
    successor_projection = (OWNER / "projections/work_analysis_operation_projection.py").read_text(
        encoding="utf-8"
    )
    for owned_operation in (
        "extract_work_facts",
        "resolve_entity_relations",
        "resolve_temporal_dependencies",
        "detect_duplicate_conflict_candidates",
        "validate_relations",
    ):
        assert f'"{owned_operation}"' not in successor_projection


def test_broad_runtime_path_is_only_a_nonsemantic_exact_graph_delegator() -> None:
    delegator = (SRC / "adapters/langgraph/subgraphs/work_analysis_workflow.py").read_text(
        encoding="utf-8"
    )
    assert (
        "from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import"
        in delegator
    )
    for forbidden in (
        "invoke_structured",
        "work_analysis.analyze",
        "WorkAnalysisAgent",
        "validate_work_analysis_result",
    ):
        assert forbidden not in delegator


def test_owner_contract_has_one_definition_and_legacy_projection_only_reexports() -> None:
    contracts = (
        SRC / "application/agents/work_analysis/contracts/work_analysis_result.py"
    ).read_text(encoding="utf-8")
    projection = (SRC / "application/orchestration/state_artifacts.py").read_text(encoding="utf-8")
    for symbol in ("WorkFactV1", "WorkRelationV1", "WorkAmbiguityV1"):
        assert contracts.count(f"class {symbol}") == 1
        assert f"class {symbol}" not in projection
