"""Route the Main graph after the Retrieval entry control."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_RETRIEVAL_ENTRY_SUCCESSORS = frozenset(
    {"single_workflow", "stage_one", "context_retriever", "domain_reconcile", "end"}
)


def route_after_retrieval_entry(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_RETRIEVAL_ENTRY_SUCCESSORS or target not in available_targets:
        raise ValueError("RETRIEVAL_ENTRY returned an unregistered successor")
    return str(target)
