from pathlib import Path


def test_plan_query_is__the_only_product_prompt__owner_in_retrieval_core() -> None:
    owner = (
        Path(__file__).resolve().parents[5] / "src/google_work_agent/application/agents/retrieval"
    )
    plan_source = (owner / "plan_query.py").read_text(encoding="utf-8")
    assert "StructuredInferencePort" in plan_source
    assert "PromptReference" in plan_source
    for operation in (
        "build_query.py",
        "execute_read.py",
        "normalize_segments.py",
        "resolve_availability.py",
        "rag_retrieve_rerank.py",
    ):
        source = (owner / operation).read_text(encoding="utf-8")
        assert "PromptReference" not in source
        assert "StructuredInferencePort" not in source
