"""Route the Main graph after initialization."""

from collections.abc import Callable, Collection, Mapping

ROUTE_AFTER_INITIALIZE_SUCCESSORS = frozenset(
    {"single_workflow", "stage_one", "request_understanding", "domain_reconcile", "end"}
)


def route_after_initialize(
    state: Mapping[str, object],
    *,
    available_targets: Collection[str],
    should_stop_for_cancel: Callable[[str], bool],
) -> str:
    target = state.get("__target__")
    run_id = state.get("run_id")
    if isinstance(run_id, str) and should_stop_for_cancel(run_id):
        return "end"
    if target not in ROUTE_AFTER_INITIALIZE_SUCCESSORS or target not in available_targets:
        raise ValueError("INITIALIZE returned an unregistered successor")
    return str(target)
