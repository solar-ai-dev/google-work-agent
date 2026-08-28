from google_work_agent.application.use_cases.llm.structured_inference_runtime import (
    _repair_prompt_id,
)


def test_initial_prompt_repairs_to_own_sibling_slot() -> None:
    assert _repair_prompt_id("planning.compose_arguments") == "planning.compose_arguments.repair"
    assert _repair_prompt_id("retrieval.select_evidence") == "retrieval.select_evidence.repair"


def test_semantic_revision_repairs_to_owning_node_repair_slot() -> None:
    assert _repair_prompt_id("retrieval.plan_query.revise") == "retrieval.plan_query.repair"
    assert (
        _repair_prompt_id("retrieval.select_evidence.revise") == "retrieval.select_evidence.repair"
    )
    assert _repair_prompt_id("planning.compose_answer.revise") == "planning.compose_answer.repair"
    assert (
        _repair_prompt_id("planning.compose_arguments.revise")
        == "planning.compose_arguments.repair"
    )


def test_recheck_repairs_to_owning_node_repair_slot() -> None:
    assert _repair_prompt_id("review.inspect.recheck") == "review.inspect.repair"
