"""Route the Main graph after Work Analysis."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_WORK_ANALYSIS_SUCCESSORS = frozenset(
    {
        "tool_route",
        "context_retriever",
        "planning",
        "retrieval_entry",
        "planning_entry",
        "stage_one",
        "stage_two",
        "single_workflow",
        "response_synthesis",
        "recovery",
        "end",
    }
)


def route_after_work_analysis(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_WORK_ANALYSIS_SUCCESSORS or target not in available_targets:
        raise ValueError("WORK_ANALYSIS returned an unregistered successor")
    return str(target)
