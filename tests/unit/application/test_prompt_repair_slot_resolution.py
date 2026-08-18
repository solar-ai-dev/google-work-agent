from google_work_agent.application.llm import _repair_prompt_id


def test_initial_prompt_repairs_to_own_sibling_slot() -> None:
    assert _repair_prompt_id("planning.compose_arguments") == "planning.compose_arguments.repair"
    assert _repair_prompt_id("retrieval.select_evidence") == "retrieval.select_evidence.repair"


def test_semantic_revision_repairs_to_owning_node_repair_slot() -> None:
    assert (
        _repair_prompt_id("tool_route.determine_io_resources.revise")
        == "tool_route.determine_io_resources.repair"
    )
    assert (
        _repair_prompt_id("tool_route.select_tool_if_needed.revise")
        == "tool_route.select_tool_if_needed.repair"
    )
    assert _repair_prompt_id("retrieval.plan_query.revise") == "retrieval.plan_query.repair"
    assert (
        _repair_prompt_id("retrieval.select_evidence.revise")
        == "retrieval.select_evidence.repair"
    )
    assert (
        _repair_prompt_id("planning.compose_answer.revise")
        == "planning.compose_answer.repair"
    )
    assert (
        _repair_prompt_id("planning.compose_arguments.revise")
        == "planning.compose_arguments.repair"
    )


def test_recheck_repairs_to_owning_node_repair_slot() -> None:
    assert _repair_prompt_id("review.inspect.recheck") == "review.inspect.repair"
