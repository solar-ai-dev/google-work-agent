"""Route the Main graph after the Review entry/settlement control."""

from collections.abc import Callable, Mapping

ROUTE_AFTER_REVIEW_ENTRY_SUCCESSORS = frozenset(
    {
        "single_workflow",
        "stage_three",
        "review",
        "retrieval_entry",
        "planning_entry",
        "domain_validation",
        "waiting_approval",
        "response_synthesis",
        "domain_reconcile",
        "end",
    }
)


def route_after_review_entry(
    state: Mapping[str, object], *, should_stop_for_cancel: Callable[[str], bool]
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_REVIEW_ENTRY_SUCCESSORS:
        raise ValueError("REVIEW_ENTRY returned an unregistered successor")
    return str(target)
